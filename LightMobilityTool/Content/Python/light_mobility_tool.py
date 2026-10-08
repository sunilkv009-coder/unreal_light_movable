"""
Light Mobility Tool
===================

Editor toggle that forces every light in every map of the project to Movable.

* ON  -> every map under MAP_ROOTS (default: /Game) is opened one by one and
         every light component (Point, Spot, Rect, Directional, Sky light,
         plus light components inside Blueprint actors) is set to Movable,
         then the map is saved. The original mobility is stored as a component
         tag so it can be put back later. While ON, lights added to whatever
         map is open are made Movable too.
* OFF -> every map is opened again, every light the tool changed is set back
         to its original mobility (Static / Stationary), the tag is removed and
         the map is saved.

Nothing moves
-------------
Only Mobility (plus a tag) is changed. After every change the tool verifies
that no actor or component moved/rotated/scaled, no attachment changed and no
other light setting changed. If anything did, the change is undone, positions
are restored, the light is skipped and its file is NOT saved. Lights with
non-movable meshes attached are skipped. Only files containing changed lights
are saved.

Works with or without source control
------------------------------------
* Connected to Perforce (or another provider) -> "source control mode" below.
* Not connected / normal project -> "local mode": files are edited and saved
  directly on disk. A file that is read-only on disk (e.g. a Perforce
  workspace opened without connecting) is never overwritten; it is skipped
  and listed in the report.

Source control mode
-------------------
* A map that is not at the latest revision, or is checked out by someone else,
  is skipped entirely and listed in the report - nothing is changed in it.
* A light is only changed after the file it is saved in (the .umap, or the
  actor's own file in __ExternalActors__ for World Partition / One File Per
  Actor) has been successfully checked out. If checkout fails, the light is
  left alone and listed in the report.
* Before saving, every modified file is checked out; anything that cannot be
  checked out is NOT saved (no read-only overwrites, no "make writable").
* Nothing is submitted. All checkouts go to your default changelist so you can
  review them in P4V and submit yourself.
* A report of everything changed / skipped is written to
  Saved/Logs/LightMobilityTool_<date>.txt and summarised in a dialog.

Use "Tools -> Light Mobility: Preview" first to see what would change without
touching any file.

Python / Output Log (Cmd -> Python):
    import light_mobility_tool as lmt
    lmt.preview_all_maps()      # read-only report
    lmt.enable()                # ON  (all maps)
    lmt.disable()               # OFF (all maps)
    lmt.enable(all_maps=False)  # ON, open level only
"""

import datetime
import json
import math
import os
import stat

import unreal

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

# Content folders searched for maps. Add e.g. "/MyPlugin" to include plugin maps.
MAP_ROOTS = ["/Game"]

# True = refuse to process all maps unless connected to source control.
# False (default) = also works on projects without source control ("local
# mode"); read-only files are still never overwritten.
REQUIRE_SOURCE_CONTROL = False

# Skip files someone else has checked out (binary files can't be merged).
SKIP_FILES_CHECKED_OUT_BY_OTHERS = True

# Skip files that are not at the latest revision (sync in P4V first).
SKIP_OUT_OF_DATE_FILES = True

# Skip a light if it has non-movable children (meshes etc. attached to it).
# Unreal can force children of a Movable component to Movable as well, which
# would change more than the light itself.
SKIP_LIGHTS_WITH_NON_MOVABLE_CHILDREN = True

# Safety check tolerances: if anything moves more than this after a change,
# the change is undone and the map is NOT saved.
POSITION_TOLERANCE = 0.001   # cm
ROTATION_TOLERANCE = 0.001   # degrees
SCALE_TOLERANCE = 0.00001

# Light settings verified to be identical before and after each change.
# (Properties a light type doesn't have are ignored.)
LIGHT_PROPERTIES_TO_VERIFY = [
    "intensity", "intensity_units", "light_color", "temperature", "use_temperature",
    "attenuation_radius", "source_radius", "soft_source_radius", "source_length",
    "source_width", "source_height", "barn_door_angle", "barn_door_length",
    "inner_cone_angle", "outer_cone_angle", "light_source_angle", "light_source_soft_angle",
    "cast_shadows", "affects_world", "visible", "hidden_in_game",
    "indirect_lighting_intensity", "volumetric_scattering_intensity", "specular_scale",
    "ies_texture", "use_ies_brightness", "ies_brightness_scale", "light_function_material",
    "lighting_channels", "atmosphere_sun_light", "source_type", "cubemap", "source_cube_map",
    "sky_distance_threshold", "lower_hemisphere_is_black", "use_inverse_squared_falloff",
    "light_falloff_exponent",
]

# World Partition maps: how many actors to load into memory at once.
WP_ACTOR_BATCH_SIZE = 500

# While enabled, the open level is re-scanned this often (seconds).
RESCAN_INTERVAL = 2.0

# Prefix of the component tag that stores the original mobility.
TAG_PREFIX = "LightMobilityTool.Original="

MENU_OWNER = "LightMobilityTool"
MENU_NAME = "LevelEditor.MainMenu.Tools"
MENU_SECTION = "LightMobilityTool"

_STATE_FILE = os.path.join(unreal.Paths.project_saved_dir(), "LightMobilityTool.json")

_MOBILITY_BY_NAME = {
    "STATIC": unreal.ComponentMobility.STATIC,
    "STATIONARY": unreal.ComponentMobility.STATIONARY,
    "MOVABLE": unreal.ComponentMobility.MOVABLE,
}

_enabled = False
_tick_handle = None
_time_since_scan = 0.0
_batch_running = False
_watcher_cache = {}
_watcher_cache_time = 0.0

# The watcher re-asks Perforce about files it couldn't check out this often.
WATCHER_RETRY_SECONDS = 60.0


# --------------------------------------------------------------------------
# Logging / report
# --------------------------------------------------------------------------

class _Report(object):
    def __init__(self, title):
        self.title = title
        self.lines = []
        self.lights_changed = 0
        self.maps_done = 0
        self.maps_skipped = []      # (map, reason)
        self.lights_skipped = []    # (light, reason)
        self.files_not_saved = []   # (file, reason)
        self.errors = []
        self.blocked_packages = set()  # files whose change failed the safety check (never saved)
        self.touched = set()        # packages this tool actually modified

    def line(self, msg):
        self.lines.append(msg)
        _log(msg)

    def skip_map(self, map_path, reason):
        self.maps_skipped.append((map_path, reason))
        unreal.log_warning("[LightMobilityTool] SKIPPED map {}: {}".format(map_path, reason))

    def skip_light(self, name, reason):
        self.lights_skipped.append((name, reason))
        unreal.log_warning("[LightMobilityTool] SKIPPED light {}: {}".format(name, reason))

    def not_saved(self, pkg, reason):
        self.files_not_saved.append((pkg, reason))
        unreal.log_error("[LightMobilityTool] NOT SAVED {}: {}".format(pkg, reason))

    def error(self, msg):
        self.errors.append(msg)
        unreal.log_error("[LightMobilityTool] " + msg)

    @property
    def has_problems(self):
        return bool(self.maps_skipped or self.lights_skipped or self.files_not_saved or self.errors)

    def text(self):
        out = [self.title, "=" * len(self.title), ""]
        out.append("Maps processed:   {}".format(self.maps_done))
        out.append("Lights changed:   {}".format(self.lights_changed))
        out.append("Maps skipped:     {}".format(len(self.maps_skipped)))
        out.append("Lights skipped:   {}".format(len(self.lights_skipped)))
        out.append("Files not saved:  {}".format(len(self.files_not_saved)))
        out.append("Errors:           {}".format(len(self.errors)))
        out.append("")
        out.append("Safety: every change was verified - no actor or component moved, no")
        out.append("attachment changed and no light setting other than Mobility changed.")
        out.append("Any change that failed this check was undone and its map was NOT saved")
        out.append("(listed under ERRORS).")
        out.append("")
        for header, items in (("SKIPPED MAPS", self.maps_skipped),
                              ("SKIPPED LIGHTS", self.lights_skipped),
                              ("FILES NOT SAVED", self.files_not_saved)):
            if items:
                out.append(header)
                out.extend("  {}  ->  {}".format(a, b) for a, b in items)
                out.append("")
        if self.errors:
            out.append("ERRORS")
            out.extend("  " + e for e in self.errors)
            out.append("")
        out.append("DETAILS")
        out.extend("  " + l for l in self.lines)
        return "\n".join(out)

    def write(self):
        log_dir = os.path.join(unreal.Paths.project_saved_dir(), "Logs")
        try:
            os.makedirs(log_dir)
        except OSError:
            pass
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(log_dir, "LightMobilityTool_{}.txt".format(stamp))
        try:
            with open(path, "w") as f:
                f.write(self.text())
        except OSError as e:
            unreal.log_error("[LightMobilityTool] Could not write report: {}".format(e))
            return None
        return os.path.abspath(path)

    def show(self):
        path = self.write()
        summary = ("Maps processed: {}\nLights changed: {}\n\n"
                   "Maps skipped: {}\nLights skipped: {}\nFiles NOT saved: {}\nErrors: {}\n"
                   .format(self.maps_done, self.lights_changed, len(self.maps_skipped),
                           len(self.lights_skipped), len(self.files_not_saved), len(self.errors)))
        if self.has_problems:
            summary += "\nSome items were skipped - see the report for the reasons.\n"
        if path:
            summary += "\nFull report:\n" + path
        unreal.EditorDialog.show_message(self.title, summary, unreal.AppMsgType.OK)


def _log(msg):
    unreal.log("[LightMobilityTool] " + msg)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _mobility_name(mobility):
    for name, value in _MOBILITY_BY_NAME.items():
        if value == mobility:
            return name
    return None


def _editor_world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _level_editor():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _level_actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def _light_components(actors=None):
    """Every light component in the level, including ones inside Blueprint actors."""
    for actor in actors if actors is not None else _level_actors():
        if actor is None:
            continue
        for comp in actor.get_components_by_class(unreal.LightComponentBase):
            yield comp


_package_fallback_used = False


def _package_name(obj):
    """Package the object is saved in (the actor's own file for One File Per Actor)."""
    global _package_fallback_used
    pkg = None
    if hasattr(obj, "get_package"):
        try:
            pkg = obj.get_package()
        except Exception:
            pkg = None
    if pkg is None:
        _package_fallback_used = True
        pkg = obj.get_outermost()
    return pkg.get_name()


def _light_label(comp):
    owner = comp.get_owner()
    owner_name = owner.get_actor_label() if owner else "?"
    return "{} ({})".format(owner_name, comp.get_name())


def _get_saved_mobility(comp):
    for tag in comp.get_editor_property("component_tags"):
        tag = str(tag)
        if tag.startswith(TAG_PREFIX):
            return _MOBILITY_BY_NAME.get(tag[len(TAG_PREFIX):])
    return None


def _set_saved_mobility(comp, mobility):
    tags = [t for t in comp.get_editor_property("component_tags") if not str(t).startswith(TAG_PREFIX)]
    if mobility is not None:
        tags.append(unreal.Name(TAG_PREFIX + _mobility_name(mobility)))
    comp.set_editor_property("component_tags", tags)


def _external_actors_prefix(map_package):
    """/Game/Maps/Foo -> /Game/__ExternalActors__/Maps/Foo/"""
    parts = map_package.split("/", 2)   # ['', 'Game', 'Maps/Foo']
    if len(parts) < 3:
        return None
    return "/{}/__ExternalActors__/{}/".format(parts[1], parts[2])


def _belongs_to_map(pkg_name, map_package):
    """True if a package is the map itself or one of its external actor files.
    Actors from streamed sub-levels / level instances belong to *their* map and
    are handled when that map is processed, so they are left alone here."""
    if pkg_name == map_package:
        return True
    prefix = _external_actors_prefix(map_package)
    return bool(prefix) and pkg_name.startswith(prefix)


def _load_state():
    try:
        with open(_STATE_FILE, "r") as f:
            return bool(json.load(f).get("enabled", False))
    except (OSError, ValueError):
        return False


def _save_state():
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({"enabled": _enabled}, f)
    except OSError as e:
        unreal.log_warning("[LightMobilityTool] Could not save state: {}".format(e))


# --------------------------------------------------------------------------
# Source control (Perforce)
# --------------------------------------------------------------------------

def source_control_enabled():
    try:
        return bool(unreal.SourceControl.is_enabled())
    except Exception:
        return False


def _query_state(pkg_name):
    try:
        state = unreal.SourceControl.query_file_state(pkg_name, True)
    except Exception:
        return None
    if state is None or not state.get_editor_property("is_valid"):
        return None
    return state


def _state_flag(state, name):
    try:
        return bool(state.get_editor_property(name))
    except Exception:
        return False


def _package_file(pkg_name):
    """Best-effort path on disk of a package (None if it can't be worked out)."""
    roots = {"Game": unreal.Paths.project_content_dir()}
    parts = pkg_name.split("/", 2)   # ['', 'Game', 'Maps/Foo']
    if len(parts) < 3:
        return None
    root = roots.get(parts[1])
    if root is None:
        # Project plugin content: Plugins/**/<Name>/Content
        plugins_dir = unreal.Paths.project_plugins_dir()
        for dirpath, dirnames, _ in os.walk(plugins_dir):
            if os.path.basename(dirpath) == parts[1] and "Content" in dirnames:
                root = os.path.join(dirpath, "Content")
                break
            if dirpath.count(os.sep) - plugins_dir.count(os.sep) > 3:
                dirnames[:] = []
    if root is None:
        return None
    base = os.path.join(unreal.Paths.convert_relative_path_to_full(root), *parts[2].split("/"))
    for ext in (".umap", ".uasset"):
        if os.path.exists(base + ext):
            return base + ext
    return None


def _check_local_file(pkg_name):
    """Local mode (no source control): only refuse files that are read-only.
    Accepts a package name (/Game/...) or an absolute file path."""
    # Package names (/Game/...) also look like absolute paths, so only treat
    # the argument as a file path when that file really exists.
    path = pkg_name if os.path.isfile(pkg_name) else _package_file(pkg_name)
    # Perforce marks files read-only via the permission bits, so check those
    # as well as os.access (which is always True for admin/root users).
    if path and (not os.access(path, os.W_OK) or not (os.stat(path).st_mode & stat.S_IWUSR)):
        return False, ("file is read-only on disk ({}). If this is a Perforce project, "
                       "connect to source control and run again".format(path))
    return True, ""


def _check_editable(pkg_name, check_out):
    """
    Returns (ok, reason). With check_out=True the file is checked out when needed.
    Without source control (local mode) the file only has to be writable.
    """
    if not source_control_enabled():
        return _check_local_file(pkg_name)

    state = _query_state(pkg_name)
    if state is None:
        # Brand-new package that isn't on disk yet, or unknown to the server.
        return True, ""

    if _state_flag(state, "is_checked_out") or _state_flag(state, "is_added"):
        return True, ""
    if not _state_flag(state, "is_source_controlled"):
        return True, ""   # local-only file, not in the depot
    if SKIP_FILES_CHECKED_OUT_BY_OTHERS and _state_flag(state, "is_checked_out_other"):
        who = ""
        try:
            who = str(state.get_editor_property("checked_out_other"))
        except Exception:
            pass
        return False, "checked out by someone else {}".format(who).strip()
    if SKIP_OUT_OF_DATE_FILES and not _state_flag(state, "is_current"):
        return False, "not at latest revision - get latest in P4V and run again"
    if _state_flag(state, "is_deleted"):
        return False, "marked for delete"
    if not check_out:
        return True, ""
    if not _state_flag(state, "can_check_out"):
        return False, "cannot be checked out"
    try:
        ok = unreal.SourceControl.check_out_file(pkg_name, True)
    except Exception as e:
        return False, "check out failed: {}".format(e)
    if not ok:
        msg = ""
        try:
            msg = str(unreal.SourceControl.last_error_msg())
        except Exception:
            pass
        return False, "check out failed {}".format(msg).strip()
    return True, ""


class _EditGuard(object):
    """Caches per-package checkout results for one pass over a level."""

    def __init__(self, report, map_package=None, cache=None):
        self.report = report
        self.map_package = map_package
        self.cache = cache if cache is not None else {}

    def allow(self, comp):
        owner = comp.get_owner() or comp
        pkg = _package_name(owner)
        if self.map_package and not _belongs_to_map(pkg, self.map_package):
            return False   # belongs to another map; handled when that map is processed
        if pkg not in self.cache:
            self.cache[pkg] = _check_editable(pkg, check_out=True)
        ok, reason = self.cache[pkg]
        if not ok and self.report is not None:
            self.report.skip_light(_light_label(comp), "{} ({})".format(reason, pkg))
        return ok


def _save_dirty(report, map_package):
    """Check out and save only the files this tool changed (the .umap, or the
    light actors' own files for World Partition). Never force-writes a read-only
    file: a package that can't be checked out is left unsaved. Anything else
    Unreal marked as modified is not saved - it is discarded when the next map
    is opened."""
    try:
        dirty = list(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
        dirty += list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
    except Exception as e:
        report.error("Could not list modified files: {}".format(e))
        return

    to_save = []
    for pkg in dirty:
        name = pkg.get_name()
        ours = name in report.touched or (
            _package_fallback_used and _belongs_to_map(name, map_package))
        if not ours:
            continue
        if name in report.blocked_packages or (
                _package_fallback_used and report.blocked_packages):
            report.not_saved(name, "safety check failed for a light in this file (see ERRORS)")
            continue
        ok, reason = _check_editable(name, check_out=True)
        if ok:
            to_save.append(pkg)
        else:
            report.not_saved(name, reason)

    if not to_save:
        return
    try:
        if not unreal.EditorLoadingAndSavingUtils.save_packages(to_save, True):
            report.error("Saving reported a failure for: {}".format(
                ", ".join(p.get_name() for p in to_save)))
    except Exception as e:
        report.error("Save failed: {}".format(e))


# --------------------------------------------------------------------------
# Core operations on the open level
# --------------------------------------------------------------------------

def _vec(v):
    return (v.x, v.y, v.z)


def _rot(r):
    """Rotation as a quaternion (x, y, z, w), same formula as FRotator::Quaternion.
    Comparing Euler angles is wrong for steep lights (a sun at -90 pitch): tiny
    float noise can swap yaw and roll completely even though nothing moved."""
    half = math.pi / 360.0
    sp, cp = math.sin(r.pitch * half), math.cos(r.pitch * half)
    sy, cy = math.sin(r.yaw * half), math.cos(r.yaw * half)
    sr, cr = math.sin(r.roll * half), math.cos(r.roll * half)
    return (cr * sp * sy - sr * cp * cy,
            -cr * sp * cy - sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy)


def _key(obj):
    try:
        return obj.get_path_name()
    except Exception:
        return str(id(obj))


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= 1e-6
        except (TypeError, ValueError):
            pass
    try:
        return bool(a == b)
    except Exception:
        return str(a) == str(b)


def _rotation_degrees(qa, qb):
    """Angle in degrees between two orientations (quaternions from _rot)."""
    dot = abs(sum(x * y for x, y in zip(qa, qb)))
    return math.degrees(2.0 * math.acos(min(1.0, dot)))


def _moved(before, after, tol, angles=False):
    if angles:
        return _rotation_degrees(before, after) > tol
    for x, y in zip(before, after):
        if abs(x - y) > tol:
            return True
    return False


def _related_actors(comps):
    """Owners of the lights plus everything attached to them, and their parents."""
    result = {}
    stack = [c.get_owner() for c in comps if c.get_owner() is not None]
    while stack:
        actor = stack.pop()
        k = _key(actor)
        if k in result:
            continue
        result[k] = actor
        try:
            stack.extend(actor.get_attached_actors())
        except Exception:
            pass
        try:
            parent = actor.get_attach_parent_actor()
            if parent is not None:
                stack.append(parent)
        except Exception:
            pass
    return list(result.values())


def _component_state(comp):
    state = {
        "loc": _vec(comp.get_world_location()),
        "rot": _rot(comp.get_world_rotation()),
        "scale": _vec(comp.get_world_scale()),
    }
    try:
        parent = comp.get_attach_parent()
        state["parent"] = _key(parent) if parent is not None else None
    except Exception:
        pass
    if isinstance(comp, unreal.LightComponentBase):
        props = {}
        for name in LIGHT_PROPERTIES_TO_VERIFY:
            try:
                props[name] = comp.get_editor_property(name)
            except Exception:
                pass
        state["props"] = props
    else:
        state["mobility"] = comp.get_editor_property("mobility")
    return state


class _Snapshot(object):
    """Positions/attachments/settings before a change, to prove nothing else changed."""

    def __init__(self, all_actors, focus_actors):
        self.actors = {}
        for a in all_actors:
            if a is None:
                continue
            try:
                self.actors[_key(a)] = (a, _vec(a.get_actor_location()), _rot(a.get_actor_rotation()),
                                        _vec(a.get_actor_scale3d()), a.get_actor_transform())
            except Exception:
                pass
        self.comps = {}
        for a in focus_actors:
            for c in a.get_components_by_class(unreal.SceneComponent):
                try:
                    self.comps[_key(c)] = (c, _component_state(c), c.get_world_transform())
                except Exception:
                    pass

    def differences(self):
        out = []
        for a, loc, rot, scale, _ in self.actors.values():
            try:
                label = a.get_actor_label()
                if _moved(loc, _vec(a.get_actor_location()), POSITION_TOLERANCE):
                    out.append("actor '{}' moved".format(label))
                if _moved(rot, _rot(a.get_actor_rotation()), ROTATION_TOLERANCE, angles=True):
                    out.append("actor '{}' rotated".format(label))
                if _moved(scale, _vec(a.get_actor_scale3d()), SCALE_TOLERANCE):
                    out.append("actor '{}' scale changed".format(label))
            except Exception:
                out.append("actor could not be checked (deleted or replaced?)")
        for c, before, _ in self.comps.values():
            try:
                after = _component_state(c)
            except Exception:
                out.append("component could not be checked (deleted or replaced?)")
                continue
            name = _light_label(c)
            if _moved(before["loc"], after["loc"], POSITION_TOLERANCE):
                out.append("{} moved".format(name))
            if _moved(before["rot"], after["rot"], ROTATION_TOLERANCE, angles=True):
                out.append("{} rotated".format(name))
            if _moved(before["scale"], after["scale"], SCALE_TOLERANCE):
                out.append("{} scale changed".format(name))
            if before.get("parent") != after.get("parent"):
                out.append("{} attachment changed".format(name))
            if "mobility" in before and before["mobility"] != after.get("mobility"):
                out.append("{} (not a light) mobility changed {} -> {}".format(
                    name, _mobility_name(before["mobility"]), _mobility_name(after.get("mobility"))))
            for prop, value in before.get("props", {}).items():
                if not _same(value, after.get("props", {}).get(prop)):
                    out.append("{} setting '{}' changed".format(name, prop))
        return out

    def restore_positions(self):
        for a, loc, rot, scale, tf in self.actors.values():
            try:
                if (_moved(loc, _vec(a.get_actor_location()), POSITION_TOLERANCE)
                        or _moved(rot, _rot(a.get_actor_rotation()), ROTATION_TOLERANCE, angles=True)
                        or _moved(scale, _vec(a.get_actor_scale3d()), SCALE_TOLERANCE)):
                    a.set_actor_transform(tf, False, True)
            except Exception:
                pass
        for c, before, tf in self.comps.values():
            try:
                after = _component_state(c)
                if (_moved(before["loc"], after["loc"], POSITION_TOLERANCE)
                        or _moved(before["rot"], after["rot"], ROTATION_TOLERANCE, angles=True)
                        or _moved(before["scale"], after["scale"], SCALE_TOLERANCE)):
                    c.set_world_transform(tf, False, True)
            except Exception:
                pass


def _non_movable_children(comp):
    """Non-light, non-editor-only components attached below this light that are
    not Movable (Unreal may force them to Movable along with the light)."""
    names = []
    try:
        children = comp.get_children_components(True)
    except Exception:
        return names
    for child in children or []:
        if isinstance(child, unreal.LightComponentBase):
            continue
        # Editor helpers (the directional light's arrow, light icon sprites) never
        # render in the game, even if they aren't flagged as editor-only.
        if any(cls is not None and isinstance(child, cls) for cls in _EDITOR_HELPER_CLASSES):
            continue
        try:
            if child.get_editor_property("is_editor_only"):
                continue
        except Exception:
            pass
        try:
            if child.get_editor_property("mobility") != unreal.ComponentMobility.MOVABLE:
                names.append(_light_label(child))
        except Exception:
            pass
    return names


_EDITOR_HELPER_CLASSES = [getattr(unreal, n, None) for n in ("ArrowComponent", "BillboardComponent")]


# Lights whose change was undone by the safety check; never retried this session.
_blocked = set()


def _apply(changes, title, report):
    """
    changes: [(component, new_mobility, new_saved_tag_mobility_or_None)]
    Applies the changes, then verifies nothing moved and no other setting changed.
    If anything did, every change is undone and positions are put back.
    Returns the number of lights changed (0 if undone).
    """
    if not changes:
        return 0
    comps = [c for c, _, _ in changes]
    before = _Snapshot(_level_actors(), _related_actors(comps))
    previous = [(c, c.get_editor_property("mobility"), list(c.get_editor_property("component_tags")))
                for c in comps]

    # One undo step for the whole batch (Ctrl+Z reverts it).
    with unreal.ScopedEditorTransaction(title):
        for comp, new_mobility, tag_mobility in changes:
            _set_saved_mobility(comp, tag_mobility)
            # set_editor_property runs PostEditChange, so the editor updates
            # lighting/shadows exactly as if you changed it in the Details panel.
            comp.set_editor_property("mobility", new_mobility)

    problems = before.differences()
    if not problems:
        if report is not None:
            for comp, _, _ in changes:
                report.touched.add(_package_name(comp.get_owner() or comp))
        return len(changes)

    # Something besides mobility changed: undo everything from this batch.
    with unreal.ScopedEditorTransaction(title + " (undone by safety check)"):
        for comp, mobility, tags in previous:
            comp.set_editor_property("component_tags", tags)
            comp.set_editor_property("mobility", mobility)
    before.restore_positions()
    still = before.differences()

    # Batch failed but undo was clean: retry one light at a time so only the
    # light(s) that actually cause the side effect are left alone.
    if len(changes) > 1 and not still:
        return sum(_apply([change], title, report) for change in changes)

    for comp in comps:
        _blocked.add(_key(comp))

    msg = ("SAFETY CHECK: changing mobility had side effects, so the change was undone: {}{}"
           .format("; ".join(sorted(set(problems))[:20]),
                   " | WARNING, still different after undo: " + "; ".join(sorted(set(still))[:20])
                   if still else ""))
    if report is not None:
        for comp in comps:
            report.blocked_packages.add(_package_name(comp.get_owner() or comp))
        report.error(msg)
    else:
        unreal.log_error("[LightMobilityTool] " + msg)
        unreal.EditorDialog.show_message(
            "Light Mobility Tool - safety check",
            msg + "\n\nDo not save this level if anything still looks wrong; "
            "reopen it without saving instead.", unreal.AppMsgType.OK)
    return 0


def make_all_lights_movable(actors=None, report=None, map_package=None, _cache=None):
    """Set every non-movable light to Movable, remembering its original mobility.
    Only Mobility (and a tag) changes; this is verified after every batch."""
    guard = _EditGuard(report, map_package, _cache)
    todo = [c for c in _light_components(actors)
            if c.get_editor_property("mobility") != unreal.ComponentMobility.MOVABLE
            and _key(c) not in _blocked]
    todo = [c for c in todo if guard.allow(c)]
    if SKIP_LIGHTS_WITH_NON_MOVABLE_CHILDREN:
        kept = []
        for c in todo:
            kids = _non_movable_children(c)
            if kids:
                reason = "has non-movable things attached ({}); they would be forced to Movable too".format(
                    ", ".join(kids[:5]))
                if report is not None:
                    report.skip_light(_light_label(c), reason)
                else:
                    unreal.log_warning("[LightMobilityTool] Skipped {}: {}".format(_light_label(c), reason))
                _blocked.add(_key(c))
            else:
                kept.append(c)
        todo = kept

    changes = []
    for comp in todo:
        current = comp.get_editor_property("mobility")
        # Only record the first original value, so a light that was Static,
        # then manually set to Stationary while the tool was on, still
        # restores to Static.
        original = _get_saved_mobility(comp) or current
        changes.append((comp, unreal.ComponentMobility.MOVABLE, original))
        if report is not None:
            report.line("  Movable: {}  (was {})".format(_light_label(comp), _mobility_name(current)))
    n = _apply(changes, "Force Lights Movable", report)
    if n:
        _log("Set {} light(s) to Movable.".format(n))
    return n


def restore_original_mobility(actors=None, report=None, map_package=None):
    """Put back the mobility of every light this tool changed."""
    guard = _EditGuard(report, map_package)
    todo = [(c, _get_saved_mobility(c)) for c in _light_components(actors)]
    todo = [(c, m) for c, m in todo if m is not None and guard.allow(c)]
    changes = []
    for comp, original in todo:
        changes.append((comp, original, None))
        if report is not None:
            report.line("  Restored: {}  -> {}".format(_light_label(comp), _mobility_name(original)))
    n = _apply(changes, "Restore Light Mobility", report)
    if n:
        _log("Restored original mobility on {} light(s).".format(n))
    return n


def _count_pending(make_movable, map_package):
    """Read-only: what would change in the open level."""
    names = []
    for comp in _light_components():
        owner = comp.get_owner() or comp
        if map_package and not _belongs_to_map(_package_name(owner), map_package):
            continue
        mobility = comp.get_editor_property("mobility")
        if make_movable and mobility != unreal.ComponentMobility.MOVABLE:
            kids = _non_movable_children(comp) if SKIP_LIGHTS_WITH_NON_MOVABLE_CHILDREN else []
            if kids:
                names.append("{}  -> WILL BE SKIPPED, non-movable things attached: {}".format(
                    _light_label(comp), ", ".join(kids[:5])))
            else:
                names.append("{}  ({})".format(_light_label(comp), _mobility_name(mobility)))
        elif not make_movable and _get_saved_mobility(comp) is not None:
            names.append(_light_label(comp))
    return names


# --------------------------------------------------------------------------
# All maps in the project
# --------------------------------------------------------------------------

def find_all_maps():
    """Package paths (e.g. /Game/Maps/MyMap) of every map under MAP_ROOTS."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.wait_for_completion()
    try:  # UE 5.1+
        ar_filter = unreal.ARFilter(
            class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "World")],
            package_paths=MAP_ROOTS, recursive_paths=True)
    except (AttributeError, TypeError):  # UE 5.0
        ar_filter = unreal.ARFilter(
            class_names=["World"], package_paths=MAP_ROOTS, recursive_paths=True)
    maps = {str(a.package_name) for a in registry.get_assets(ar_filter)}
    # Never touch engine/temporary/external-actor packages.
    return sorted(m for m in maps if "/__External" not in m and not m.startswith("/Temp/"))


def _world_partition_actor_guids():
    """Guids of every actor in the open World Partition map ([] if it isn't one)."""
    lib = getattr(unreal, "WorldPartitionBlueprintLibrary", None)
    if lib is None:
        return []
    try:
        result = lib.get_actor_descs()
    except Exception:
        return []
    # Depending on engine version this is either the list or (success, list).
    if isinstance(result, tuple):
        result = result[-1]
    guids = []
    for desc in result or []:
        try:
            guids.append(desc.get_editor_property("guid"))
        except Exception:
            pass
    return guids


def _process_open_map(map_path, make_movable, report, dry_run):
    func = make_all_lights_movable if make_movable else restore_original_mobility
    seen = set()   # dry run: lights that stay loaded across WP batches count once

    def one_pass():
        if dry_run:
            names = [n for n in _count_pending(make_movable, map_path) if n not in seen]
            seen.update(names)
            for n in names:
                report.line("  would change: " + n)
            return len([n for n in names if "WILL BE SKIPPED" not in n])
        n = func(report=report, map_package=map_path)
        if n:
            _save_dirty(report, map_path)
        report.touched.clear()
        report.blocked_packages.clear()
        return n

    count = one_pass()

    guids = _world_partition_actor_guids()
    if guids:
        report.line("  World Partition map: {} actors, loading in batches of {}".format(
            len(guids), WP_ACTOR_BATCH_SIZE))
        lib = unreal.WorldPartitionBlueprintLibrary
        for i in range(0, len(guids), WP_ACTOR_BATCH_SIZE):
            batch = guids[i:i + WP_ACTOR_BATCH_SIZE]
            lib.load_actors(batch)
            try:
                count += one_pass()
            finally:
                lib.unload_actors(batch)
    return count


def process_all_maps(make_movable=True, maps=None, dry_run=False, show_report=True):
    """
    Open every map, make its lights Movable (or restore them), check out and
    save the changed files. With dry_run=True nothing is changed or checked out.
    Returns the report.
    """
    global _batch_running

    title = "Light Mobility Tool - {}{}".format(
        "Preview " if dry_run else "",
        "Make Movable" if make_movable else "Restore")
    report = _Report(title)
    level_editor = _level_editor()

    if level_editor.is_in_play_in_editor():
        report.error("Stop Play-In-Editor first.")
        if show_report:
            report.show()
        return report

    if not dry_run and REQUIRE_SOURCE_CONTROL and not source_control_enabled():
        report.error("Not connected to source control and REQUIRE_SOURCE_CONTROL is True. "
                     "Connect (Revision Control button, bottom-right of the editor) and run again.")
        if show_report:
            report.show()
        return report

    report.line("Mode: {}".format(
        "source control (files are checked out before saving)" if source_control_enabled()
        else "local - no source control connected (files saved directly; read-only files skipped)"))

    # Let the user save (or not) whatever they were working on before we switch maps.
    if not unreal.EditorLoadingAndSavingUtils.save_dirty_packages_with_dialog(True, True):
        report.error("Cancelled by user at the save prompt.")
        return report

    world = _editor_world()
    start_map = world.get_outermost().get_name() if world else None
    maps = maps if maps is not None else find_all_maps()
    report.line("Maps found: {}".format(len(maps)))

    _batch_running = True
    try:
        verb = "Previewing" if dry_run else ("Making lights Movable" if make_movable else "Restoring lights")
        with unreal.ScopedSlowTask(len(maps), verb + " in all maps...") as task:
            task.make_dialog(True)
            for map_path in maps:
                if task.should_cancel():
                    report.error("Cancelled by user after {} map(s).".format(report.maps_done))
                    break
                task.enter_progress_frame(1, "{}: {}".format(verb, map_path))

                # Check the map file before opening it. Out of date / locked
                # maps are skipped completely.
                ok, reason = _check_editable(map_path, check_out=False)
                if not ok:
                    report.skip_map(map_path, reason)
                    continue

                try:
                    if not level_editor.load_level(map_path):
                        report.skip_map(map_path, "could not be opened")
                        continue
                    report.line(map_path)
                    count = _process_open_map(map_path, make_movable, report, dry_run)
                    report.lights_changed += count
                    report.maps_done += 1
                except Exception as e:
                    report.error("{}: {}".format(map_path, e))
    finally:
        _batch_running = False
        if start_map and start_map.startswith("/") and not start_map.startswith("/Temp/"):
            try:
                level_editor.load_level(start_map)
            except Exception:
                pass

    _log("Done: {} light(s) across {} map(s).".format(report.lights_changed, report.maps_done))
    if show_report:
        report.show()
    return report


def preview_all_maps():
    """Read-only: open every map and report which lights would change. Nothing is
    modified, checked out or saved."""
    return process_all_maps(make_movable=not _enabled, dry_run=True)


# --------------------------------------------------------------------------
# Watcher: keeps new / changed lights Movable while enabled
# --------------------------------------------------------------------------

def _on_tick(delta_seconds):
    global _time_since_scan, _watcher_cache_time

    _time_since_scan += delta_seconds
    if _time_since_scan < RESCAN_INTERVAL:
        return
    _time_since_scan = 0.0

    if _batch_running or _editor_world() is None:
        return
    # Don't touch anything while Play-In-Editor is running.
    if _level_editor().is_in_play_in_editor():
        return
    # Remember checkout results for a while so a file locked by someone else
    # isn't queried on the Perforce server every couple of seconds.
    _watcher_cache_time += RESCAN_INTERVAL
    if _watcher_cache_time >= WATCHER_RETRY_SECONDS:
        _watcher_cache.clear()
        _watcher_cache_time = 0.0
    try:
        # Lights in files locked by others / out of date are skipped here too.
        make_all_lights_movable(_cache=_watcher_cache)
    except Exception as e:
        unreal.log_warning("[LightMobilityTool] Rescan failed: {}".format(e))


def _start_watcher():
    global _tick_handle, _time_since_scan
    if _tick_handle is None:
        _time_since_scan = 0.0
        _tick_handle = unreal.register_slate_post_tick_callback(_on_tick)


def _stop_watcher():
    global _tick_handle
    if _tick_handle is not None:
        unreal.unregister_slate_post_tick_callback(_tick_handle)
        _tick_handle = None


# --------------------------------------------------------------------------
# Public on/off API
# --------------------------------------------------------------------------

def is_enabled():
    return _enabled


def _confirm(message):
    answer = unreal.EditorDialog.show_message(
        "Light Mobility Tool", message, unreal.AppMsgType.YES_NO)
    return answer == unreal.AppReturnType.YES


def _mode_text():
    if source_control_enabled():
        return ("Source control is connected:\n"
                "- Changed maps are checked out (default changelist) and saved.\n"
                "- Nothing is submitted; review and submit yourself.\n"
                "- Maps that are out of date or checked out by someone else are skipped.\n")
    return ("No source control connected - LOCAL MODE:\n"
            "- Changed maps are saved directly to disk. Back up the project first.\n"
            "- Read-only files are skipped (never overwritten). If this is a Perforce\n"
            "  project, click No and connect to source control first.\n")


def _source_control_ok():
    if REQUIRE_SOURCE_CONTROL and not source_control_enabled():
        unreal.EditorDialog.show_message(
            "Light Mobility Tool",
            "Not connected to source control (REQUIRE_SOURCE_CONTROL is True).\n\n"
            "Connect first (Revision Control button, bottom-right of the editor), then try again.",
            unreal.AppMsgType.OK)
        return False
    return True


def enable(all_maps=True, ask=True):
    """Turn ON: make every light in every map Movable (or just the open level)."""
    global _enabled
    if all_maps:
        if not _source_control_ok():
            return
        maps = find_all_maps()
        if ask and not _confirm(
                "Set every light to Movable in all {} map(s) under {}?\n\n{}\n"
                "- Original mobility is remembered, so turning the tool off restores it.\n\n"
                "Tip: run 'Light Mobility: Preview' first to see what will change."
                .format(len(maps), ", ".join(MAP_ROOTS), _mode_text())):
            return
        process_all_maps(True, maps)
    else:
        make_all_lights_movable()
    _enabled = True
    _save_state()
    _start_watcher()
    _log("ON - all lights are forced to Movable.")


def disable(all_maps=True, ask=True):
    """Turn OFF: restore the original mobility in every map (or just the open level)."""
    global _enabled
    maps = None
    if all_maps:
        if not _source_control_ok():
            return
        maps = find_all_maps()
        if ask and not _confirm(
                "Restore every light's original mobility in all {} map(s)?\n\n{}"
                .format(len(maps), _mode_text())):
            return
    _enabled = False
    _save_state()
    _stop_watcher()
    if all_maps:
        process_all_maps(False, maps)
    else:
        restore_original_mobility()
    _log("OFF - original light mobility restored.")


def toggle():
    if _enabled:
        disable()
    else:
        enable()


# --------------------------------------------------------------------------
# Menu entries (Tools menu)
# --------------------------------------------------------------------------

@unreal.uclass()
class LightMobilityToggleEntry(unreal.ToolMenuEntryScript):

    @unreal.ufunction(override=True)
    def execute(self, context):
        toggle()

    @unreal.ufunction(override=True)
    def get_check_state(self, context):
        return unreal.CheckBoxState.CHECKED if _enabled else unreal.CheckBoxState.UNCHECKED


@unreal.uclass()
class LightMobilityPreviewEntry(unreal.ToolMenuEntryScript):

    @unreal.ufunction(override=True)
    def execute(self, context):
        preview_all_maps()


def _register_menu():
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_NAME)
    if menu is None:
        unreal.log_warning("[LightMobilityTool] Could not find menu '{}'.".format(MENU_NAME))
        return

    menu.add_section(MENU_SECTION, "Lighting")

    toggle_entry = LightMobilityToggleEntry()
    toggle_entry.init_entry(
        MENU_OWNER, MENU_NAME, MENU_SECTION,
        "ForceLightsMovable",
        "Force Lights Movable (All Maps)",
        "When checked, every light in every map is set to Movable (no Static/Stationary). "
        "Changed maps are checked out in Perforce and saved. Uncheck to restore.",
    )
    advanced = toggle_entry.data.advanced
    advanced.user_interface_action_type = unreal.UserInterfaceActionType.TOGGLE_BUTTON
    toggle_entry.data.advanced = advanced
    menu.add_menu_entry_object(toggle_entry)

    preview_entry = LightMobilityPreviewEntry()
    preview_entry.init_entry(
        MENU_OWNER, MENU_NAME, MENU_SECTION,
        "PreviewLightMobility",
        "Light Mobility: Preview (no changes)",
        "Opens every map and lists which lights would change. Nothing is modified, "
        "checked out or saved.",
    )
    menu.add_menu_entry_object(preview_entry)

    menus.refresh_all_widgets()


def startup():
    """Called from init_unreal.py when the editor starts."""
    global _enabled
    _register_menu()
    _enabled = _load_state()
    if _enabled:
        # Level may not be loaded yet; the watcher applies it on the first scan.
        _start_watcher()
        _log("Restored ON state from last session.")
