"""
Performance Improvements
========================

Backend for the "Performance Improvements" editor tab (C++ UI plugin
PerformanceOptimizerUI) and for the fallback entries in the Tools menu.

Every optimization is an *item* with a name, a description, a visual-impact
rating and a scan that checks whether it is already in place:

* Toggle items change a console variable (project rendering setting) or, for
  one item, a property on lights in the open level.
* Advice items only scan and explain; they never change anything (used where an
  automatic change would alter the look of the production).

Production safety ("tread lightly")
-----------------------------------
* Textures are never touched. Texture-related settings (streaming pool, mip
  bias, anisotropy, virtual textures, texture LOD) are on a hard deny list and
  can't be changed by this tool. A read-only check reports anything in the
  project that already lowers texture quality.
* Toggling only changes the running editor session. Nothing is written to the
  project until you press "Save to Project", which writes only marked lines in
  Config/DefaultEngine.ini [SystemSettings] (checked out in Perforce first,
  backed up to Saved/PerformanceOptimizer/Backups, and every line records the
  previous value so it can be removed exactly).
* Restarting the editor discards everything that wasn't saved.
* Auto Optimize only uses items with NO visual impact, unless you explicitly
  allow "Low" impact items. It never edits levels and never saves.
* The level item (volumetric fog shadows) only changes the open level, is a
  single undo step (Ctrl+Z), is verified with the Light Mobility Tool safety
  check (nothing moves, no other setting changes) and is not saved for you.

Python / Output Log (Cmd -> Python):
    import perf_optimizer as po
    po.ui_scan()                     # scan, writes Saved/PerformanceOptimizer/ui_state.json
    po.ui_set("lumen_gi_probes", True)
    po.ui_measure()                  # measure editor FPS
    po.ui_auto_start()               # measure -> apply safe items -> measure
    po.ui_save_project()             # write enabled settings to DefaultEngine.ini
    po.ui_revert_all()               # turn off everything this tool turned on
"""

import datetime
import json
import os
import re
import sys
import traceback

import unreal

import light_mobility_tool as lmt

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

STREAM_FPS = 60                    # frame rate your pixel stream runs at
SCREEN_PERCENTAGE = 75             # internal resolution for the upscaling item
MAX_SHADOWED_LOCAL_LIGHTS = 8      # more than this -> suggest fewer / MegaLights
LARGE_ATTENUATION_RADIUS = 3000.0  # cm
HIGH_POLY_VERTS = 100000           # meshes above this without Nanite are reported
MANY_MESH_COMPONENTS = 10000       # draw-call warning threshold

# FPS measurement (editor viewport).
WARMUP_SECONDS = 3.0
SAMPLE_SECONDS = 5.0
STABLE_TOLERANCE = 0.05            # 5% between 1-second windows counts as settled
SETTLE_TIMEOUT = 45.0

# Hard guard: the tool can never change any of these (texture quality).
TEXTURE_CVAR_DENYLIST = re.compile(
    r"^(r\.Streaming\.|r\.TextureStreaming|r\.MipMapLODBias|r\.MaxAnisotropy|"
    r"r\.VirtualTexture|r\.VT\.|r\.TextureLOD|r\.Texture)", re.IGNORECASE)

RISK_LEVELS = ["None", "Low", "Medium", "High"]

INI_SECTION = "[SystemSettings]"
INI_MARKER = "; [PerformanceOptimizer]"
TAG_PREFIX = "PerfOptimizer."

MENU_NAME = "LevelEditor.MainMenu.Tools"
MENU_SECTION = "PerformanceOptimizer"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _log(msg):
    unreal.log("[PerformanceOptimizer] " + msg)


def _data_dir():
    path = os.path.join(unreal.Paths.project_saved_dir(), "PerformanceOptimizer")
    try:
        os.makedirs(path)
    except OSError:
        pass
    return path


def _state_file():
    return os.path.join(_data_dir(), "ui_state.json")


def _session_file():
    return os.path.join(_data_dir(), "session.json")


def _config_file():
    config_dir = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_config_dir())
    return os.path.join(config_dir, "DefaultEngine.ini")


def _stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _prop(obj, name, default=None):
    try:
        return obj.get_editor_property(name)
    except Exception:
        return default


def _fmt(value):
    if value is None:
        return "?"
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return ("%.4f" % value).rstrip("0").rstrip(".")


def _engine_version():
    try:
        m = re.match(r"(\d+)\.(\d+)", str(unreal.SystemLibrary.get_engine_version()))
        return int(m.group(1)), int(m.group(2))
    except Exception:
        return 5, 0


def _in_pie():
    try:
        return lmt._level_editor().is_in_play_in_editor()
    except Exception:
        return False


def _cvar_get(name):
    try:
        return float(unreal.SystemLibrary.get_console_variable_float_value(name))
    except Exception:
        return None


def _cvar_set(name, value):
    if TEXTURE_CVAR_DENYLIST.match(name):
        raise RuntimeError("Refusing to change texture setting " + name)
    unreal.SystemLibrary.execute_console_command(lmt._editor_world(), "{} {}".format(name, _fmt(value)))


def _actor_label(actor):
    try:
        return actor.get_actor_label()
    except Exception:
        return str(actor)


def _components(actor, class_name):
    cls = getattr(unreal, class_name, None)
    if cls is None or actor is None:
        return []
    try:
        return list(actor.get_components_by_class(cls))
    except Exception:
        return []


def _is_instance(obj, class_name):
    cls = getattr(unreal, class_name, None)
    return cls is not None and isinstance(obj, cls)


def _confirm(title, message):
    answer = unreal.EditorDialog.show_message(title, message, unreal.AppMsgType.YES_NO)
    return answer == unreal.AppReturnType.YES


def _info(title, message):
    unreal.EditorDialog.show_message(title, message, unreal.AppMsgType.OK)


# --------------------------------------------------------------------------
# Session state (what this tool changed in the running editor)
# --------------------------------------------------------------------------

_session = {"cvars": {}}   # item id -> value before this tool changed it


def _save_session():
    try:
        with open(_session_file(), "w") as f:
            json.dump(_session, f, indent=1)
    except OSError as e:
        unreal.log_warning("[PerformanceOptimizer] Could not save session: {}".format(e))


# --------------------------------------------------------------------------
# DefaultEngine.ini editing (only our own marked lines)
# --------------------------------------------------------------------------

_MARKER_RE = re.compile(
    r"^; \[PerformanceOptimizer\] cvar=(?P<cvar>\S+) runtime_before=(?P<rt>\S+) ini_before=(?P<ini>.*)$")


def _ini_read():
    path = _config_file()
    try:
        # newline="" keeps \r\n as-is, so saving never rewrites the whole file's line endings
        with open(path, "r", newline="") as f:
            text = f.read()
    except OSError:
        return [], "\n"
    newline = "\r\n" if "\r\n" in text else "\n"
    return text.splitlines(), newline


def _ini_markers(lines):
    """cvar -> (line index, runtime value before, original ini line or None)"""
    out = {}
    for i, line in enumerate(lines):
        m = _MARKER_RE.match(line.strip())
        if m:
            rt = m.group("rt")
            ini = m.group("ini")
            out[m.group("cvar")] = (i, None if rt == "?" else float(rt), None if ini == "NONE" else ini)
    return out


def _ini_section_range(lines):
    start = -1
    for i, line in enumerate(lines):
        if line.strip() == INI_SECTION:
            start = i
            break
    if start < 0:
        return -1, -1
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip().startswith("["):
            end = i
            break
    return start, end


def _ini_set(lines, cvar, value, runtime_before):
    markers = _ini_markers(lines)
    if cvar in markers:
        idx = markers[cvar][0]
        if idx + 1 < len(lines) and lines[idx + 1].split("=", 1)[0].strip().lower() == cvar.lower():
            lines[idx + 1] = "{}={}".format(cvar, _fmt(value))
            return
        del lines[idx]   # damaged block: rebuild it below

    start, end = _ini_section_range(lines)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(INI_SECTION)
        start, end = len(lines) - 1, len(lines)

    def marker(ini_before):
        return "{} cvar={} runtime_before={} ini_before={}".format(
            INI_MARKER, cvar, _fmt(runtime_before) if runtime_before is not None else "?", ini_before)

    # An existing line for this cvar written by someone else: replace it in
    # place, remembering it exactly so removing our setting puts it back.
    for i in range(start + 1, end):
        text = lines[i].strip()
        if text and not text.startswith(";") and text.split("=", 1)[0].strip().lower() == cvar.lower():
            lines[i:i + 1] = [marker(lines[i]), "{}={}".format(cvar, _fmt(value))]
            return

    pos = end
    while pos - 1 > start and not lines[pos - 1].strip():
        pos -= 1
    lines[pos:pos] = [marker("NONE"), "{}={}".format(cvar, _fmt(value))]


def _ini_remove(lines, cvar):
    markers = _ini_markers(lines)
    if cvar not in markers:
        return False
    idx, _, ini_before = markers[cvar]
    count = 2 if (idx + 1 < len(lines) and
                  lines[idx + 1].split("=", 1)[0].strip().lower() == cvar.lower()) else 1
    del lines[idx:idx + count]
    if ini_before is not None:
        lines.insert(idx, ini_before)
    return True


def _ini_write(lines, newline):
    path = _config_file()
    ok, reason = lmt._check_editable(path, check_out=True)
    if not ok:
        return False, "Cannot write {}: {}".format(path, reason)
    backup_dir = os.path.join(_data_dir(), "Backups")
    try:
        os.makedirs(backup_dir)
    except OSError:
        pass
    backup = os.path.join(backup_dir, "DefaultEngine_{}.ini".format(_stamp()))
    try:
        if os.path.exists(path):
            with open(path, "rb") as src, open(backup, "wb") as dst:
                dst.write(src.read())
        with open(path, "w", newline="") as f:
            f.write(newline.join(lines) + newline)
    except OSError as e:
        return False, "Could not write {}: {}".format(path, e)
    return True, backup


# --------------------------------------------------------------------------
# Scan context
# --------------------------------------------------------------------------

class _Ctx(object):
    """Everything a scan needs, collected once."""

    def __init__(self):
        self.version = _engine_version()
        world = lmt._editor_world()
        self.level = world.get_outermost().get_name() if world else "(no level open)"
        self.actors = [a for a in lmt._level_actors() if a is not None]
        self.lights = list(lmt._light_components(self.actors))
        self.local_lights = [l for l in self.lights if _is_instance(l, "LocalLightComponent")]
        self.sky_lights = [l for l in self.lights if _is_instance(l, "SkyLightComponent")]
        self.fogs = [c for a in self.actors for c in _components(a, "ExponentialHeightFogComponent")]
        self.ppvs = [a for a in self.actors if _is_instance(a, "PostProcessVolume")]
        self.markers = _ini_markers(_ini_read()[0])
        self._cvars = {}

    def cvar(self, name):
        if name not in self._cvars:
            self._cvars[name] = _cvar_get(name)
        return self._cvars[name]

    @property
    def shadowed_local_lights(self):
        return [l for l in self.local_lights if _prop(l, "cast_shadows", False)]

    @property
    def volumetric_fog(self):
        return any(_prop(f, "enable_volumetric_fog", False) or _prop(f, "volumetric_fog", False)
                   for f in self.fogs)


def _owners(comps):
    seen, out = set(), []
    for c in comps:
        owner = c.get_owner()
        if owner is not None and lmt._key(owner) not in seen:
            seen.add(lmt._key(owner))
            out.append(owner)
    return out


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------

class _Item(object):
    kind = "toggle"
    scope = "Project setting"
    textures = "Not affected"

    def __init__(self, id, category, name, detail, risk, gain, auto=False):
        assert risk in RISK_LEVELS
        self.id, self.category, self.name, self.detail = id, category, name, detail
        self.risk, self.gain, self.auto = risk, gain, auto
        self.affects_measurement = False
        self.game_only = False

    def scan(self, ctx):
        raise NotImplementedError

    def apply(self, ctx, on):
        return False, "This item can't be toggled."

    def candidates(self, ctx):
        return []

    def to_json(self, ctx):
        data = {
            "id": self.id, "name": self.name, "detail": self.detail, "kind": self.kind,
            "visual_risk": self.risk, "gain": self.gain, "scope": self.scope,
            "textures": self.textures, "auto": self.auto,
            "enabled": False, "available": False, "status": "info", "suggestion": "",
            "can_select": False, "ours": False, "saved": False, "unsaved": False,
        }
        try:
            data.update(self.scan(ctx))
        except Exception as e:
            data.update(status="warn", suggestion="Could not check this item: {}".format(e))
        return data


class _CvarItem(_Item):
    """A console variable written to [SystemSettings] when saved."""

    def __init__(self, id, category, name, detail, risk, gain, cvar, value, mode="eq",
                 why="", auto=False, game_only=False, affects_measurement=False,
                 requires=None, min_version=None, textures="Not affected"):
        _Item.__init__(self, id, category, name, detail, risk, gain, auto)
        if TEXTURE_CVAR_DENYLIST.match(cvar):
            raise ValueError("Texture settings are not allowed in this tool: " + cvar)
        self.cvar, self.value, self.mode, self.why = cvar, value, mode, why
        self.game_only = game_only
        self.affects_measurement = affects_measurement
        self.requires = requires
        self.min_version = min_version
        self.textures = textures
        self.scope = "Project setting (game/stream only)" if game_only else "Project setting"

    def is_on(self, cur):
        if cur is None:
            return False
        if self.mode == "eq":
            return abs(cur - self.value) < 1e-4
        if self.mode == "ge":
            return cur >= self.value - 1e-4
        if self.mode == "le":       # negative means "engine default / post-process volume"
            return 0 <= cur <= self.value + 1e-4
        if self.mode == "cap":      # 0 means "no cap"
            return 0 < cur <= self.value + 1e-4
        return False

    def applicable(self, ctx):
        if self.min_version and ctx.version < self.min_version:
            return False, "Needs Unreal Engine {}.{} or newer (this is {}.{}).".format(
                self.min_version[0], self.min_version[1], ctx.version[0], ctx.version[1])
        if self.requires:
            return self.requires(ctx)
        return True, ""

    def ours(self, ctx):
        return self.id in _session["cvars"] or self.cvar in ctx.markers

    def previous_value(self, ctx):
        if self.id in _session["cvars"]:
            return _session["cvars"][self.id]
        if self.cvar in ctx.markers:
            return ctx.markers[self.cvar][1]
        return None

    def scan(self, ctx):
        cur = ctx.cvar(self.cvar)
        on = self.is_on(cur)
        ours = self.ours(ctx)
        saved = self.cvar in ctx.markers
        unsaved = (on and ours and not saved) or (saved and not on)
        ok, why_not = self.applicable(ctx)
        result = {"enabled": on, "ours": ours, "saved": saved, "unsaved": unsaved}
        save_note = ""
        if unsaved:
            save_note = (" Not saved to the project yet - press 'Save to Project' to keep it."
                         if on else " Still in DefaultEngine.ini - press 'Save to Project' to remove it.")
        if not ok:
            result.update(available=on and ours, status="na",
                          suggestion="Not applicable: " + why_not + save_note)
        elif on:
            who = "Set by this tool." if ours else "Already set in your project - nothing to do."
            result.update(available=ours, status="ok", suggestion="Active: {} = {}. {}{}".format(
                self.cvar, _fmt(cur), who, save_note))
        else:
            result.update(available=True, status="suggest", suggestion=(
                "Not enabled: {} is {}. Turn on to set it to {}. {}{}".format(
                    self.cvar, _fmt(cur), _fmt(self.value), self.why, save_note)).strip())
        return result

    def apply(self, ctx, on):
        cur = ctx.cvar(self.cvar)
        if on:
            ok, why_not = self.applicable(ctx)
            if not ok:
                return False, why_not
            if self.is_on(cur):
                return True, "{} is already {}.".format(self.cvar, _fmt(cur))
            if self.id not in _session["cvars"]:
                _session["cvars"][self.id] = cur
                _save_session()
            _cvar_set(self.cvar, self.value)
        else:
            if not self.is_on(cur):
                return True, "Already off."
            prev = self.previous_value(ctx)
            if prev is None:
                return False, ("{} was already set this way before this tool changed anything "
                               "(project config or scalability), so the tool won't change it."
                               .format(self.cvar))
            _cvar_set(self.cvar, prev)
            _session["cvars"].pop(self.id, None)
            _save_session()

        after = _cvar_get(self.cvar)
        target = self.value if on else self.previous_value(ctx)
        if on and not self.is_on(after):
            return False, ("Unreal did not accept {} = {} while the editor is running (it may be "
                           "read-only). Save to Project and restart the editor to use it."
                           .format(self.cvar, _fmt(self.value)))
        if not on and target is not None and after is not None and abs(after - target) > 1e-4:
            return False, "Could not restore {} to {}.".format(self.cvar, _fmt(target))
        return True, "{} = {}".format(self.cvar, _fmt(after))


class _VolumetricShadowItem(_Item):
    """Level item: turn off 'Cast Volumetric Shadow' on local lights."""

    scope = "Open level (not saved for you)"
    prop = "cast_volumetric_shadow"

    def _tag(self):
        return TAG_PREFIX + self.id + "="

    def _tagged(self, ctx):
        out = []
        for l in ctx.local_lights:
            for t in _prop(l, "component_tags", []) or []:
                if str(t).startswith(self._tag()):
                    out.append((l, str(t)[len(self._tag()):] == "True"))
        return out

    def candidates(self, ctx):
        return [l for l in ctx.local_lights
                if _prop(l, self.prop, False) and _prop(l, "cast_shadows", False)
                and (_prop(l, "volumetric_scattering_intensity", 1.0) or 0) > 0]

    def scan(self, ctx):
        cands = self.candidates(ctx)
        tagged = self._tagged(ctx)
        result = {"enabled": bool(tagged) and not cands, "ours": bool(tagged),
                  "can_select": bool(cands or tagged)}
        if not ctx.volumetric_fog:
            result.update(available=bool(tagged), status="na", suggestion=(
                "Not applicable: this level has no volumetric fog, so these shadows cost nothing."))
        elif not cands:
            result.update(available=bool(tagged), status="ok", suggestion=(
                "Active: no local light casts volumetric fog shadows{}."
                .format(" (set by this tool on {} light(s) - save the level to keep it)".format(len(tagged))
                        if tagged else "")))
        else:
            result.update(available=True, status="suggest", suggestion=(
                "{} local light(s) cast shadows into volumetric fog. Turn on to switch that off "
                "(the lights themselves and their normal shadows stay unchanged). Changes only the "
                "open level; Ctrl+Z undoes it; save the level yourself to keep it.".format(len(cands))))
        return result

    def apply(self, ctx, on):
        if on:
            comps = self.candidates(ctx)
            if not comps:
                return True, "Nothing to change."
            changes = [(c, False, self._tag() + str(bool(_prop(c, self.prop, False)))) for c in comps]
        else:
            tagged = self._tagged(ctx)
            if not tagged:
                return True, "Nothing to restore."
            changes = [(c, original, None) for c, original in tagged]
        return _apply_light_changes(changes, self.prop, self._tag(),
                                    "Perf: volumetric shadows " + ("off" if on else "restore"))


def _apply_light_changes(changes, prop, tag_prefix, title):
    """changes: [(component, new value, new tag or None)]. Verified with the
    Light Mobility Tool snapshot: if anything else changes, everything is undone."""
    comps = [c for c, _, _ in changes]
    before = lmt._Snapshot(lmt._level_actors(), lmt._related_actors(comps))
    previous = [(c, _prop(c, prop), list(_prop(c, "component_tags", []) or [])) for c in comps]
    with unreal.ScopedEditorTransaction(title):
        for comp, value, tag in changes:
            tags = [t for t in (_prop(comp, "component_tags", []) or []) if not str(t).startswith(tag_prefix)]
            if tag:
                tags.append(unreal.Name(tag))
            comp.set_editor_property("component_tags", tags)
            comp.set_editor_property(prop, value)
    problems = before.differences()
    if not problems:
        return True, "Changed {} light(s) in the open level (Ctrl+Z to undo).".format(len(changes))
    with unreal.ScopedEditorTransaction(title + " (undone by safety check)"):
        for comp, value, tags in previous:
            comp.set_editor_property("component_tags", tags)
            comp.set_editor_property(prop, value)
    before.restore_positions()
    return False, "Safety check failed, change undone: " + "; ".join(sorted(set(problems))[:10])


class _AdviceItem(_Item):
    """Scan-only item. `check(ctx)` -> (status, suggestion, candidate actors)."""

    kind = "advice"

    def __init__(self, id, category, name, detail, risk, gain, check, scope="Open level (read-only)"):
        _Item.__init__(self, id, category, name, detail, risk, gain, auto=False)
        self.check = check
        self.scope = scope

    def candidates(self, ctx):
        return self.check(ctx)[2]

    def scan(self, ctx):
        status, suggestion, actors = self.check(ctx)
        return {"available": False, "status": status, "suggestion": suggestion,
                "can_select": bool(actors), "enabled": status == "ok"}


# ---- requirement checks -------------------------------------------------

def _req_vsm(ctx):
    return (ctx.cvar("r.Shadow.Virtual.Enable") == 1,
            "Virtual Shadow Maps are off in this project.")


def _req_lumen_gi(ctx):
    return (ctx.cvar("r.DynamicGlobalIlluminationMethod") == 1, "Lumen global illumination is not used.")


def _req_lumen_reflections(ctx):
    return (ctx.cvar("r.ReflectionMethod") == 1, "Lumen reflections are not used.")


def _req_ray_tracing(ctx):
    return (ctx.cvar("r.RayTracing") == 1, "Hardware ray tracing is off in this project.")


def _req_sky_realtime(ctx):
    using = [s for s in ctx.sky_lights if _prop(s, "real_time_capture", False)]
    return (bool(using), "No Sky Light in this level uses Real Time Capture - nothing to gain.")


def _req_many_lights(ctx):
    n = len(ctx.shadowed_local_lights)
    return (n > MAX_SHADOWED_LOCAL_LIGHTS,
            "Only {} shadow-casting local light(s) in this level; MegaLights pays off with many.".format(n))


# ---- advice checks -------------------------------------------------------

def _check_shadowed_lights(ctx):
    lights = ctx.shadowed_local_lights
    owners = _owners(lights)
    if len(lights) <= MAX_SHADOWED_LOCAL_LIGHTS:
        return "ok", "{} shadow-casting local light(s) - fine.".format(len(lights)), owners
    return "suggest", (
        "{} local lights cast shadows. Shadows are the main cost of Movable lights. Review fill/rim/"
        "accent lights and switch off 'Cast Shadows' where it isn't visible (use 'Select in level', "
        "then edit them together in the Details panel). Not automatic: only you can judge which "
        "shadows matter for the look.".format(len(lights))), owners


def _check_attenuation(ctx):
    big = [l for l in ctx.local_lights if (_prop(l, "attenuation_radius", 0) or 0) > LARGE_ATTENUATION_RADIUS]
    if not big:
        return "ok", "No local light has an attenuation radius above {} cm.".format(
            int(LARGE_ATTENUATION_RADIUS)), []
    return "suggest", (
        "{} local light(s) have an attenuation radius above {} cm. A light costs per pixel it "
        "covers; tightening the radius to where the light is actually visible is often a large win "
        "with no visible change. Review with 'Select in level'.".format(len(big), int(LARGE_ATTENUATION_RADIUS))), _owners(big)


def _check_light_functions(ctx):
    lf = [l for l in ctx.lights if _prop(l, "light_function_material") is not None]
    if not lf:
        return "ok", "No light uses a light function.", []
    return "suggest", (
        "{} light(s) use a light function material, which is expensive (especially with shadows). "
        "Consider an IES profile or a texture-based gobo alternative.".format(len(lf))), _owners(lf)


def _check_bloom(ctx):
    fft = getattr(getattr(unreal, "BloomMethod", None), "BM_FFT", None)
    bad = []
    for v in ctx.ppvs:
        settings = _prop(v, "settings")
        if settings is not None and fft is not None and _prop(settings, "override_bloom_method", False) \
                and _prop(settings, "bloom_method") == fft:
            bad.append(v)
    if not bad:
        return "ok", "No post-process volume uses Convolution (FFT) bloom.", []
    return "suggest", (
        "{} post-process volume(s) use Convolution bloom, which is expensive. Standard bloom is much "
        "cheaper but looks different - compare before switching.".format(len(bad))), bad


def _check_nanite(ctx):
    sub = getattr(unreal, "StaticMeshEditorSubsystem", None)
    counter = None
    if sub is not None:
        try:
            counter = unreal.get_editor_subsystem(sub).get_number_verts
        except Exception:
            counter = None
    if counter is None and getattr(unreal, "EditorStaticMeshLibrary", None) is not None:
        counter = unreal.EditorStaticMeshLibrary.get_number_verts
    if counter is None:
        return "info", "Can't count mesh vertices in this engine version.", []
    meshes = {}
    for a in ctx.actors:
        for c in _components(a, "StaticMeshComponent"):
            if _is_instance(c, "InstancedStaticMeshComponent"):
                continue
            mesh = _prop(c, "static_mesh")
            if mesh is not None:
                meshes.setdefault(lmt._key(mesh), (mesh, []))[1].append(a)
    heavy, actors = [], []
    for mesh, users in meshes.values():
        nanite = _prop(_prop(mesh, "nanite_settings"), "enabled", False)
        if nanite:
            continue
        try:
            verts = counter(mesh, 0)
        except Exception:
            continue
        if verts >= HIGH_POLY_VERTS:
            heavy.append("{} ({:,} verts)".format(mesh.get_name(), verts))
            actors.extend(users)
    if not heavy:
        return "ok", "No mesh above {:,} vertices is missing Nanite.".format(HIGH_POLY_VERTS), []
    return "suggest", (
        "{} high-poly mesh(es) don't use Nanite: {}{}. Enabling Nanite on opaque CAD parts keeps the "
        "full detail and usually cuts GPU and draw cost a lot. Glass/translucent and masked parts "
        "should stay non-Nanite. This changes the mesh assets, so it's left to you."
        .format(len(heavy), ", ".join(heavy[:5]), "..." if len(heavy) > 5 else "")), actors


def _check_mesh_count(ctx):
    count = 0
    for a in ctx.actors:
        for c in _components(a, "StaticMeshComponent"):
            if not _is_instance(c, "InstancedStaticMeshComponent"):
                count += 1
    if count <= MANY_MESH_COMPONENTS:
        return "ok", "{:,} static mesh components - fine.".format(count), []
    return "suggest", (
        "{:,} separate static mesh components (CAD imports often split cars into thousands of parts). "
        "That's many draw calls on the CPU. Merge parts that never move separately, or use Nanite / "
        "instancing.".format(count)), []


def _check_textures(ctx):
    """Read-only texture quality guard. Never changes anything."""
    problems = []
    mip_bias = ctx.cvar("r.Streaming.MipBias")
    if mip_bias is not None and mip_bias > 0:
        problems.append("r.Streaming.MipBias = {} (above 0 lowers texture resolution)".format(_fmt(mip_bias)))
    aniso = ctx.cvar("r.MaxAnisotropy")
    if aniso is not None and 0 < aniso < 8:
        problems.append("r.MaxAnisotropy = {} (8-16 keeps textures sharp at angles)".format(_fmt(aniso)))
    pool = ctx.cvar("r.Streaming.PoolSize")
    pool_note = " Texture streaming pool: {} MB.".format(_fmt(pool)) if pool else ""
    if not problems:
        return "ok", ("No setting in this project lowers texture quality. This tool never changes "
                      "texture settings." + pool_note), []
    return "warn", ("These settings lower texture quality: " + "; ".join(problems) +
                    ". This tool will not change them - review them in your project config." + pool_note), []


# ---- the catalog ---------------------------------------------------------

CAT_STREAM = "Frame pacing & pixel streaming"
CAT_RES = "Resolution"
CAT_SHADOW = "Shadows & lights"
CAT_LUMEN = "Global illumination & reflections (Lumen)"
CAT_POST = "Post processing"
CAT_GEO = "Geometry & draw calls"
CAT_TEX = "Texture quality guard"

ITEMS = [
    _CvarItem("fps_cap", CAT_STREAM, "Cap frame rate to the stream rate ({} FPS)".format(STREAM_FPS),
              "Frames rendered above the stream rate are never sent. Capping frees the GPU for the "
              "video encoder, keeps frame pacing even and lowers heat/throttling on the server.",
              "None", "Stability", "t.MaxFPS", STREAM_FPS, mode="cap", auto=True,
              affects_measurement=True,
              why="Steadier stream and more GPU headroom for the encoder."),
    _CvarItem("vsync_off", CAT_STREAM, "VSync off",
              "Pixel streaming renders off-screen; VSync only adds latency and can halve the frame "
              "rate when it misses a refresh.",
              "None", "Medium", "r.VSync", 0, auto=True, game_only=True, affects_measurement=True,
              why="Lower latency, no frame-rate halving."),
    _CvarItem("screen_percentage", CAT_RES,
              "Render at {}% and upscale (TSR / DLSS)".format(SCREEN_PERCENTAGE),
              "Renders fewer pixels and upscales to the output resolution. Usually the biggest single "
              "FPS gain, but it softens fine texture detail - with textures being important, compare "
              "close-ups (badges, stitching, paint flakes) before keeping it. Also make sure the game "
              "resolution matches the stream resolution.",
              "High", "Very high", "r.ScreenPercentage", SCREEN_PERCENTAGE, mode="cap",
              game_only=True, textures="Softer (lower internal resolution)",
              why="Large GPU saving; check texture sharpness first."),
    _CvarItem("vsm_cache", CAT_SHADOW, "Virtual Shadow Map caching",
              "Reuses shadow pages that didn't change since last frame. Invisible quality-wise.",
              "None", "High", "r.Shadow.Virtual.Cache", 1, auto=True, requires=_req_vsm,
              why="Shadow work is only redone where something moved."),
    _CvarItem("vsm_local_lod", CAT_SHADOW, "Lighter shadow resolution for local lights",
              "Renders point/spot/rect light shadows one resolution step lower. Shadows get very "
              "slightly softer; usually invisible after video compression.",
              "Low", "Medium", "r.Shadow.Virtual.ResolutionLodBiasLocal", 1, mode="ge", auto=True,
              requires=_req_vsm, why="Fewer shadow pages to render for every local light."),
    _CvarItem("vsm_local_rays", CAT_SHADOW, "Fewer soft-shadow rays for local lights",
              "Uses 4 rays per pixel for local light soft shadows (default is higher). Penumbras get "
              "slightly noisier; TSR mostly hides it.",
              "Low", "Low", "r.Shadow.Virtual.SMRT.RayCountLocal", 4, mode="le", auto=True,
              requires=_req_vsm, why="Cheaper shadow filtering per light."),
    _CvarItem("rt_shadows_off", CAT_SHADOW, "Use Virtual Shadow Maps instead of ray-traced shadows",
              "Ray-traced shadows cost more than VSMs for every shadowed light. Contact and soft "
              "shadow look changes slightly.",
              "Medium", "High", "r.RayTracing.Shadows", 0, requires=_req_ray_tracing,
              why="Big saving with many shadowed lights."),
    _CvarItem("megalights", CAT_SHADOW, "MegaLights",
              "UE 5.5+ system for many shadow-casting lights at a fixed cost. Changes how shadows and "
              "noise look - test carefully before using in production.",
              "High", "Very high (many lights)", "r.MegaLights.EnableForProject", 1,
              requires=_req_many_lights, min_version=(5, 5),
              why="Shadow cost stops growing with the number of lights."),
    _CvarItem("skylight_realtime", CAT_SHADOW, "Sky Light: no real-time recapture",
              "Real-time capture re-renders the sky light every frame. If the sky/HDRI doesn't change "
              "at runtime this is wasted work. Leave off if you animate time of day.",
              "Medium", "Medium", "r.SkyLight.RealTimeReflectionCapture", 0, requires=_req_sky_realtime,
              why="Saves a full sky capture every frame."),
    _VolumetricShadowItem("volumetric_shadow_off", CAT_SHADOW, "Local lights: no volumetric fog shadows",
                          "Shadowed lights inside volumetric fog render extra shadow work for the fog.",
                          "Low", "Medium"),
    _AdviceItem("shadowed_lights", CAT_SHADOW, "Number of shadow-casting lights",
                "Every shadow-casting Movable light costs shadow rendering each frame.",
                "Medium", "Very high", _check_shadowed_lights),
    _AdviceItem("attenuation", CAT_SHADOW, "Oversized light radius",
                "Light cost scales with the screen area inside its attenuation radius.",
                "Low", "High", _check_attenuation),
    _AdviceItem("light_functions", CAT_SHADOW, "Light functions",
                "Light function materials are evaluated per pixel per light.",
                "Medium", "Medium", _check_light_functions),
    _CvarItem("lumen_gi_probes", CAT_LUMEN, "Lumen GI: fewer screen probes",
              "Places Lumen GI probes every 32 pixels instead of 16. Indirect light gets slightly "
              "smoother; direct light, reflections and textures are unchanged.",
              "Low", "High", "r.Lumen.ScreenProbeGather.DownsampleFactor", 32, mode="ge", auto=True,
              requires=_req_lumen_gi, why="Roughly a quarter of the GI probe work."),
    _CvarItem("lumen_reflection_roughness", CAT_LUMEN, "Lumen reflections: trace only glossy surfaces",
              "Surfaces rougher than 0.3 use cheaper reflections. Car paint, chrome and glass are glossy "
              "and keep traced reflections; only rough materials (tyres, fabric, plastics) change, "
              "very subtly.",
              "Low", "Medium", "r.Lumen.Reflections.MaxRoughnessToTrace", 0.3, mode="le", auto=True,
              requires=_req_lumen_reflections, why="Fewer reflection rays on matte surfaces."),
    _CvarItem("motion_blur_off", CAT_POST, "Motion blur off",
              "Video encoding already smears motion; motion blur adds GPU cost and makes the stream "
              "blurrier. Keep it if your cinematics depend on it.",
              "Low", "Low", "r.MotionBlurQuality", 0, auto=True,
              why="Sharper stream, small GPU saving."),
    _CvarItem("lens_flare_off", CAT_POST, "Lens flares off",
              "Image-based lens flares cost a few passes per frame. Turn off unless the look uses them.",
              "Low", "Low", "r.LensFlareQuality", 0, auto=True, why="Small GPU saving."),
    _AdviceItem("bloom", CAT_POST, "Convolution bloom",
                "FFT/convolution bloom is one of the most expensive post effects.",
                "Medium", "Medium", _check_bloom),
    _AdviceItem("nanite", CAT_GEO, "High-poly meshes without Nanite",
                "Nanite renders dense CAD meshes efficiently at full detail.",
                "None", "High", _check_nanite, scope="Open level (read-only, changes are asset edits)"),
    _AdviceItem("mesh_count", CAT_GEO, "Draw calls (number of mesh parts)",
                "Each separate mesh part is CPU work every frame.",
                "None", "Medium", _check_mesh_count),
    _AdviceItem("texture_guard", CAT_TEX, "Texture quality",
                "Checks that nothing in the project lowers texture quality. This tool never changes "
                "texture settings.",
                "None", "-", _check_textures, scope="Project (read-only)"),
]

_ITEMS_BY_ID = {i.id: i for i in ITEMS}
CATEGORY_ORDER = [CAT_STREAM, CAT_RES, CAT_SHADOW, CAT_LUMEN, CAT_POST, CAT_GEO, CAT_TEX]


def _auto_items(ctx, include_low):
    max_risk = RISK_LEVELS.index("Low" if include_low else "None")
    out = []
    for item in ITEMS:
        if not item.auto or item.kind != "toggle" or not isinstance(item, _CvarItem):
            continue
        if RISK_LEVELS.index(item.risk) > max_risk or item.textures != "Not affected":
            continue
        ok, _ = item.applicable(ctx)
        if ok and not item.is_on(ctx.cvar(item.cvar)):
            out.append(item)
    return out


# --------------------------------------------------------------------------
# UI state (read by the C++ tab)
# --------------------------------------------------------------------------

_busy = False
_progress = ""
_message = ""
_last_items = []
_last_ctx_info = {}
_results = None
_results_text = ""
_last_measure = None
_last_report = None


def _write_state(ctx=None):
    global _last_items, _last_ctx_info
    if ctx is not None:
        cats = []
        for name in CATEGORY_ORDER:
            items = [i.to_json(ctx) for i in ITEMS if i.category == name]
            if items:
                cats.append({"name": name, "items": items})
        _last_items = cats
        _last_ctx_info = {
            "level": ctx.level,
            "engine": "{}.{}".format(*ctx.version),
            "mode": "Perforce/source control connected" if lmt.source_control_enabled()
            else "No source control (local files)",
        }
    unsaved = any(it.get("unsaved") for c in _last_items for it in c["items"])
    suggestions = sum(1 for c in _last_items for it in c["items"] if it.get("status") in ("suggest", "warn"))
    header = ("Level: {}   |   Engine {}   |   {}\n"
              "Toggles only change this editor session. Nothing is written to the project until you "
              "press 'Save to Project'. Textures are never changed.".format(
                  _last_ctx_info.get("level", "?"), _last_ctx_info.get("engine", "?"),
                  _last_ctx_info.get("mode", "?")))
    status = _progress if _busy else (_message or "{} suggestion(s) found.".format(suggestions))
    if unsaved and not _busy:
        status += "   |   Unsaved project setting changes."
    state = {
        "version": 1, "busy": _busy, "header_text": header, "status_text": status,
        "results_text": _results_text, "results": _results, "unsaved": unsaved,
        "report_path": _last_report or "", "categories": _last_items,
    }
    path = _state_file()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        unreal.log_warning("[PerformanceOptimizer] Could not write UI state: {}".format(e))
    return state


def _guard(fn):
    """UI entry points never raise; errors are shown in the tab and logged."""
    def wrapper(*args, **kwargs):
        global _message, _busy
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            _message = "Error: {} (details in the Output Log)".format(e)
            unreal.log_error("[PerformanceOptimizer] " + traceback.format_exc())
            if _busy and _measure is None:
                # Failed before a measurement got going: don't leave the tab stuck.
                _busy = False
                try:
                    _restore_caps()
                except Exception:
                    pass
            try:
                _write_state(_Ctx())
            except Exception:
                _write_state()
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


# --------------------------------------------------------------------------
# FPS measurement (editor viewport, uncapped)
# --------------------------------------------------------------------------

_tick_handle = None
_measure = None


class _Measurement(object):
    def __init__(self, label, on_done):
        self.label, self.on_done = label, on_done
        self.phase = "settle"
        self.elapsed = 0.0
        self.win_time, self.win_frames = 0.0, 0
        self.prev_fps, self.stable = None, 0
        self.samples, self.sample_time = [], 0.0
        self.unstable = False
        self.last_write = 0.0

    def step(self, dt):
        global _progress
        if dt <= 0:
            return
        if self.phase == "settle":
            self.elapsed += dt
            self.win_time += dt
            self.win_frames += 1
            if self.win_time >= 1.0:
                fps = self.win_frames / self.win_time
                if self.prev_fps and abs(fps - self.prev_fps) / self.prev_fps <= STABLE_TOLERANCE:
                    self.stable += 1
                else:
                    self.stable = 0
                self.prev_fps = fps
                self.win_time, self.win_frames = 0.0, 0
            if self.elapsed >= SETTLE_TIMEOUT:
                self.unstable = True
                self.phase = "sample"
            elif self.elapsed >= WARMUP_SECONDS and self.stable >= 1:
                self.phase = "sample"
            _progress = ("Measuring {}: waiting for the frame rate to settle ({:.0f}s)... "
                         "Keep the editor focused and don't move the camera.".format(self.label, self.elapsed))
        else:
            self.samples.append(dt)
            self.sample_time += dt
            _progress = "Measuring {}: {:.1f} / {:.0f} s... don't move the camera.".format(
                self.label, self.sample_time, SAMPLE_SECONDS)
            if self.sample_time >= SAMPLE_SECONDS:
                self.finish()
                return
        self.last_write += dt
        if self.last_write >= 0.5:
            self.last_write = 0.0
            _write_state()

    def finish(self):
        global _measure
        _measure = None
        s = self.samples
        total = sum(s)
        worst = sorted(s, reverse=True)[:max(1, len(s) // 100)]
        result = {
            "label": self.label, "fps": len(s) / total, "ms": total / len(s) * 1000.0,
            "low1_fps": len(worst) / sum(worst), "max_ms": max(s) * 1000.0,
            "frames": len(s), "unstable": self.unstable,
        }
        self.on_done(result)


def _on_tick(delta_seconds):
    if _measure is None:
        return
    try:
        _measure.step(delta_seconds)
    except Exception:
        unreal.log_error("[PerformanceOptimizer] " + traceback.format_exc())
        _abort("Measurement failed - see the Output Log.")


def _ensure_tick():
    global _tick_handle
    if _tick_handle is None:
        _tick_handle = unreal.register_slate_post_tick_callback(_on_tick)


_caps = None


def _uncap():
    """Measure the real GPU/CPU cost, not a frame cap."""
    global _caps
    _caps = {}
    for name in ("t.MaxFPS", "r.VSyncEditor"):
        _caps[name] = _cvar_get(name)
        _cvar_set(name, 0)


def _restore_caps():
    global _caps
    if _caps:
        for name, value in _caps.items():
            if value is not None:
                _cvar_set(name, value)
    _caps = None


def _abort(message):
    global _busy, _measure, _message, _progress
    _measure = None
    _restore_caps()
    _busy = False
    _progress = ""
    _message = message
    _write_state(_Ctx())


def _measure_preflight(viewport_realtime):
    if _busy:
        return "Busy - wait for the current operation to finish."
    if _in_pie():
        return "Stop Play-In-Editor first."
    if viewport_realtime is False:
        return ("The level viewport is not in Realtime mode, so the editor isn't rendering every "
                "frame and FPS can't be measured. Turn on Realtime (Ctrl+R in the viewport) and try again.")
    return None


def _fmt_result(r):
    return "{:.1f} FPS ({:.2f} ms, worst 1%: {:.1f} FPS)".format(r["fps"], r["ms"], r["low1_fps"])


def _compare_text(before, after):
    change = (after["fps"] - before["fps"]) / before["fps"] * 100.0
    return "BEFORE {}   ->   AFTER {}   =   {:+.1f}% FPS".format(_fmt_result(before), _fmt_result(after), change), change


# --------------------------------------------------------------------------
# UI entry points
# --------------------------------------------------------------------------

@_guard
def ui_scan():
    """Scan the project settings and the open level."""
    global _message
    if not _busy:
        _message = ""
    return _write_state(_Ctx())


@_guard
def ui_set(item_id, on):
    """Turn an item on/off in the running editor session."""
    global _message
    item = _ITEMS_BY_ID.get(item_id)
    if item is None or _busy:
        _message = "Busy - try again in a moment." if _busy else "Unknown item: {}".format(item_id)
        return _write_state(_Ctx())
    if _in_pie():
        _message = "Stop Play-In-Editor first."
        return _write_state(_Ctx())
    ok, msg = item.apply(_Ctx(), bool(on))
    _message = "{}: {}".format(item.name, msg) if ok else "{} - NOT changed: {}".format(item.name, msg)
    if ok:
        _log(_message)
    else:
        unreal.log_warning("[PerformanceOptimizer] " + _message)
    return _write_state(_Ctx())


@_guard
def ui_select(item_id):
    """Select the actors an item refers to, so they can be reviewed in the Details panel."""
    global _message
    item = _ITEMS_BY_ID.get(item_id)
    ctx = _Ctx()
    actors = []
    if item is not None:
        for c in item.candidates(ctx):
            actors.append(c.get_owner() if hasattr(c, "get_owner") and not _is_instance(c, "Actor") else c)
        if isinstance(item, _VolumetricShadowItem):
            actors += [c.get_owner() for c, _ in item._tagged(ctx)]
    unique, seen = [], set()
    for a in actors:
        if a is not None and lmt._key(a) not in seen:
            seen.add(lmt._key(a))
            unique.append(a)
    unreal.get_editor_subsystem(unreal.EditorActorSubsystem).set_selected_level_actors(unique)
    _message = "Selected {} actor(s) for '{}'.".format(len(unique), item.name if item else item_id)
    return _write_state(ctx)


@_guard
def ui_save_project():
    """Write enabled settings to DefaultEngine.ini and remove ones that were turned off."""
    global _message
    if _busy:
        return _write_state()
    ctx = _Ctx()
    lines, newline = _ini_read()
    if not lines and not os.path.exists(_config_file()):
        _message = "Could not find {}.".format(_config_file())
        return _write_state(ctx)
    added, removed = [], []
    for item in ITEMS:
        if not isinstance(item, _CvarItem):
            continue
        cur = ctx.cvar(item.cvar)
        on = item.is_on(cur)
        if on and item.ours(ctx):
            _ini_set(lines, item.cvar, item.value, item.previous_value(ctx))
            added.append("{}={}".format(item.cvar, _fmt(item.value)))
        elif not on and item.cvar in ctx.markers:
            _ini_remove(lines, item.cvar)
            removed.append(item.cvar)
    original, _ = _ini_read()
    if lines == original:
        _message = "Nothing to save - the project config already matches."
        return _write_state(ctx)
    summary = []
    if added:
        summary.append("Write / keep:\n  " + "\n  ".join(added))
    if removed:
        summary.append("Remove (restores the previous line if there was one):\n  " + "\n  ".join(removed))
    if not _confirm("Save to Project",
                    "Update {}\n[SystemSettings]?\n\n{}\n\n"
                    "The file is checked out first (Perforce) and backed up to "
                    "Saved/PerformanceOptimizer/Backups. Nothing is submitted. These settings also "
                    "apply to packaged / pixel-streaming builds.".format(_config_file(), "\n\n".join(summary))):
        _message = "Save cancelled."
        return _write_state(ctx)
    ok, info = _ini_write(lines, newline)
    if ok:
        _message = "Saved to DefaultEngine.ini (backup: {}). Submit it in P4V when you're happy.".format(info)
        _log(_message)
    else:
        _message = "NOT saved: " + info
        unreal.log_error("[PerformanceOptimizer] " + _message)
    return _write_state(_Ctx())


@_guard
def ui_revert_all():
    """Turn off everything this tool turned on (session). Use Save to Project to also clean the config."""
    global _message
    if _busy:
        return _write_state()
    ctx = _Ctx()
    reverted, failed = [], []
    for item in ITEMS:
        if item.kind != "toggle":
            continue
        data = item.scan(ctx)
        if not (data.get("ours") and data.get("enabled")) and not (
                isinstance(item, _VolumetricShadowItem) and data.get("ours")):
            continue
        ok, msg = item.apply(ctx, False)
        (reverted if ok else failed).append(item.name if ok else "{} ({})".format(item.name, msg))
        ctx = _Ctx()
    ctx = _Ctx()
    unsaved = any(isinstance(i, _CvarItem) and i.cvar in ctx.markers for i in ITEMS)
    _message = "Reverted {} item(s).".format(len(reverted))
    if failed:
        _message += " Could not revert: " + "; ".join(failed)
    if unsaved:
        _message += " Settings are still in DefaultEngine.ini - press 'Save to Project' to remove them."
    return _write_state(ctx)


@_guard
def ui_measure(viewport_realtime=None):
    """Measure editor viewport FPS (uncapped) and compare with the previous measurement."""
    global _busy, _message, _results_text, _results
    problem = _measure_preflight(viewport_realtime)
    if problem:
        _message = problem
        return _write_state(_Ctx())

    def done(result):
        global _busy, _message, _results_text, _results, _last_measure
        _restore_caps()
        if _last_measure:
            text, change = _compare_text(_last_measure, result)
            _results_text = "Since last measurement: " + text
        else:
            _results_text = "Measured: " + _fmt_result(result) + "   (measure again after changes to compare)"
        if result["unstable"]:
            _results_text += "   [frame rate never settled - numbers are rough]"
        _results = {"before": _last_measure, "after": result}
        _last_measure = result
        _busy = False
        _message = "Measurement finished."
        _write_state(_Ctx())

    _busy = True
    _uncap()
    _ensure_tick()
    _start(_Measurement("current settings", done))
    return _write_state()


def _start(measurement):
    global _measure
    _measure = measurement


@_guard
def ui_auto_start(viewport_realtime=None, include_low=False, ask=True, show_dialog=False):
    """Measure -> apply the safe items -> measure, and report the FPS change."""
    global _busy, _message, _results_text, _results
    problem = _measure_preflight(viewport_realtime)
    if problem:
        _message = problem
        return _write_state(_Ctx())
    ctx = _Ctx()
    items = _auto_items(ctx, include_low)
    if not items:
        _message = ("Nothing left for Auto Optimize ({} visual impact allowed). Everything safe is "
                    "already on - see the suggestions for manual options.".format(
                        "None/Low" if include_low else "no"))
        return _write_state(ctx)
    listing = "\n".join("  - {}  [visual change: {}]".format(i.name, i.risk) for i in items)
    if ask and not _confirm(
            "Auto Optimize",
            "Auto Optimize will:\n"
            "1. measure the editor viewport FPS (about {:.0f}-{:.0f} s),\n"
            "2. turn on these settings for THIS EDITOR SESSION ONLY:\n{}\n"
            "3. measure again and show the difference.\n\n"
            "Textures are never changed. Levels are not edited. Nothing is saved - use 'Save to "
            "Project' afterwards to keep them, or 'Revert All' to undo.\n\n"
            "Keep the editor focused and don't move the viewport camera while it measures."
            "{}\n\nContinue?".format(
                WARMUP_SECONDS + SAMPLE_SECONDS, 2 * (WARMUP_SECONDS + SAMPLE_SECONDS) + 5, listing,
                "" if viewport_realtime else "\nMake sure the viewport is in Realtime mode (Ctrl+R).")):
        _message = "Auto Optimize cancelled."
        return _write_state(ctx)

    _busy = True
    _uncap()
    _ensure_tick()
    in_frame = [i for i in items if not i.affects_measurement]
    after_frame = [i for i in items if i.affects_measurement]
    applied, failed = [], []

    def after_before(before):
        c = _Ctx()
        for item in in_frame:
            ok, msg = item.apply(c, True)
            (applied if ok else failed).append(item.name if ok else "{} ({})".format(item.name, msg))
        _write_state()
        _start(_Measurement("AFTER", lambda after: after_after(before, after)))

    def after_after(before, after):
        global _busy, _message, _results_text, _results, _last_measure, _last_report
        _restore_caps()
        c = _Ctx()
        for item in after_frame:
            ok, msg = item.apply(c, True)
            (applied if ok else failed).append(item.name if ok else "{} ({})".format(item.name, msg))
        text, change = _compare_text(before, after)
        notes = []
        if before["unstable"] or after["unstable"]:
            notes.append("The frame rate never fully settled - repeat the run for reliable numbers.")
        if after_frame:
            notes.append("Not in the numbers (game/stream pacing only): " + ", ".join(i.name for i in after_frame) + ".")
        notes.append("Measured in the editor viewport, uncapped, same camera. A packaged pixel-streaming "
                     "build will differ, but the relative change is a good guide.")
        _results_text = text + "\n" + " ".join(notes)
        _results = {"before": before, "after": after, "change_pct": change,
                    "applied": applied, "failed": failed}
        _last_measure = after
        _last_report = _write_report("Auto Optimize", before, after, change, applied, failed, notes)
        _busy = False
        _message = "Auto Optimize finished: {:+.1f}% FPS. Applied {} setting(s) for this session - " \
                   "'Save to Project' to keep, 'Revert All' to undo.".format(change, len(applied))
        if failed:
            _message += " Not applied: " + "; ".join(failed)
        _log(_message)
        _write_state(_Ctx())
        if show_dialog:
            _info("Auto Optimize", _results_text + "\n\nApplied: " + ", ".join(applied) +
                  "\n\nReport: " + str(_last_report))

    _start(_Measurement("BEFORE", after_before))
    return _write_state()


@_guard
def ui_cancel():
    """Stop a running measurement. Settings already applied stay on (use Revert All)."""
    _abort("Cancelled. Settings that were already applied stay on for this session (Revert All undoes them).")
    return _write_state()


@_guard
def ui_open_report():
    global _message
    path = _last_report
    if not path or not os.path.exists(path):
        path = _write_scan_report(_Ctx())
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])
        _message = "Opened report: " + path
    except Exception as e:
        _message = "Report saved at {} ({})".format(path, e)
    return _write_state()


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

def _write_report(title, before, after, change, applied, failed, notes):
    path = os.path.join(_data_dir(), "Report_{}.txt".format(_stamp()))
    lines = [title, "=" * len(title), "",
             "Before: " + _fmt_result(before),
             "After:  " + _fmt_result(after),
             "Change: {:+.1f}% FPS".format(change), "",
             "Applied (editor session only, not saved):"]
    lines += ["  - " + a for a in applied] or ["  (none)"]
    if failed:
        lines += ["", "Not applied:"] + ["  - " + f for f in failed]
    lines += ["", "Notes:"] + ["  - " + n for n in notes]
    lines += ["", "Textures: no texture setting was changed (enforced by the tool)."]
    lines += ["", _scan_text(_Ctx())]
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return os.path.abspath(path)


def _scan_text(ctx):
    out = ["SCAN - level {}".format(ctx.level), ""]
    for name in CATEGORY_ORDER:
        rows = [i.to_json(ctx) for i in ITEMS if i.category == name]
        if not rows:
            continue
        out.append(name.upper())
        for r in rows:
            flag = {"ok": "OK  ", "suggest": "TODO", "warn": "WARN", "na": "N/A ", "info": "INFO"}.get(r["status"], "    ")
            out.append("  [{}] {}  (visual change: {}, gain: {})".format(flag, r["name"], r["visual_risk"], r["gain"]))
            out.append("         " + r["suggestion"])
        out.append("")
    return "\n".join(out)


def _write_scan_report(ctx):
    path = os.path.join(_data_dir(), "Scan_{}.txt".format(_stamp()))
    with open(path, "w") as f:
        f.write(_scan_text(ctx))
    return os.path.abspath(path)


# --------------------------------------------------------------------------
# Fallback Tools-menu entries (work without the C++ tab)
# --------------------------------------------------------------------------

@_guard
def menu_scan_report():
    ctx = _Ctx()
    _write_state(ctx)
    path = _write_scan_report(ctx)
    todo = sum(1 for c in _last_items for it in c["items"] if it["status"] in ("suggest", "warn"))
    _info("Performance Improvements - Scan",
          "{} suggestion(s) for level {}.\n\nFull report:\n{}".format(todo, ctx.level, path))


@_guard
def menu_auto():
    include_low = _confirm(
        "Auto Optimize",
        "Also include settings with LOW visual impact?\n\n"
        "Yes = also slightly softer local-light shadows / GI, motion blur and lens flares off.\n"
        "No  = only settings with no visual impact.\n\nTextures are never changed either way.")
    ui_auto_start(viewport_realtime=None, include_low=include_low, ask=True, show_dialog=True)


@unreal.uclass()
class PerfScanEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        menu_scan_report()


@unreal.uclass()
class PerfAutoEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        menu_auto()


@unreal.uclass()
class PerfRevertEntry(unreal.ToolMenuEntryScript):
    @unreal.ufunction(override=True)
    def execute(self, context):
        ui_revert_all()
        _info("Performance Improvements", _message)


def _register_menu():
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_NAME)
    if menu is None:
        return
    menu.add_section(MENU_SECTION, "Performance")
    for cls, name, label, tip in (
            (PerfScanEntry, "PerfScan", "Performance: Scan (report)",
             "Scan project settings and the open level for performance improvements. Read-only."),
            (PerfAutoEntry, "PerfAuto", "Performance: Auto Optimize (session only)",
             "Measure FPS, apply safe settings for this session, measure again."),
            (PerfRevertEntry, "PerfRevert", "Performance: Revert All",
             "Turn off everything the performance tool turned on in this session.")):
        entry = cls()
        entry.init_entry("PerformanceOptimizer", MENU_NAME, MENU_SECTION, name, label, tip)
        menu.add_menu_entry_object(entry)
    menus.refresh_all_widgets()


def startup():
    """Called from init_unreal.py. Runtime changes don't survive a restart, so
    the session record starts empty."""
    global _session
    _session = {"cvars": {}}
    _save_session()
    _ensure_tick()
    _register_menu()
