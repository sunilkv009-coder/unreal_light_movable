"""Logic tests for perf_optimizer using a fake `unreal` module.
Run: python3 tests/test_perf.py
They check decisions (what is changed, saved, reverted, measured); they don't
replace a test inside the real editor."""
import json
import os
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "LightMobilityTool", "Content", "Python"))

import unreal as U  # noqa: E402
import light_mobility_tool as lmt  # noqa: E402
import perf_optimizer as po  # noqa: E402

M = U.ComponentMobility
S = U.STATE

DEFAULT_CVARS = {
    "t.MaxFPS": 0, "r.VSync": 1, "r.VSyncEditor": 1, "r.ScreenPercentage": 100,
    "r.Shadow.Virtual.Enable": 1, "r.Shadow.Virtual.Cache": 1,
    "r.Shadow.Virtual.ResolutionLodBiasLocal": 0, "r.Shadow.Virtual.SMRT.RayCountLocal": 7,
    "r.RayTracing": 0, "r.RayTracing.Shadows": 0,
    "r.DynamicGlobalIlluminationMethod": 1, "r.ReflectionMethod": 1,
    "r.Lumen.ScreenProbeGather.DownsampleFactor": 16, "r.Lumen.Reflections.MaxRoughnessToTrace": -1,
    "r.MotionBlurQuality": 4, "r.LensFlareQuality": 2, "r.SkyLight.RealTimeReflectionCapture": 1,
    "r.MegaLights.EnableForProject": 0,
    # texture settings - must never change
    "r.Streaming.MipBias": 0, "r.MaxAnisotropy": 8, "r.Streaming.PoolSize": 3000,
}
TEXTURE_KEYS = ["r.Streaming.MipBias", "r.MaxAnisotropy", "r.Streaming.PoolSize"]

INI = "\r\n".join([
    "[/Script/Engine.RendererSettings]",
    "r.DefaultFeature.AutoExposure=False",
    "",
    "[SystemSettings]",
    "r.Lumen.ScreenProbeGather.DownsampleFactor=24",
    "r.SomethingElse=1",
    "",
    "[/Script/EngineSettings.GameMapsSettings]",
    "GameDefaultMap=/Game/Maps/Showroom",
    "",
])


def reset():
    U.CVARS.clear()
    U.CVARS.update(DEFAULT_CVARS)
    U.READ_ONLY.clear()
    U.DIALOGS.clear()
    S.sc = False
    S.files = {}
    S.checkouts = []
    S.pie = False
    S.selected = []
    ini = os.path.join(U.CONFIG, "DefaultEngine.ini")
    if os.path.exists(ini):
        os.chmod(ini, stat.S_IREAD | stat.S_IWRITE)
    with open(ini, "w", newline="") as f:
        f.write(INI)
    car = U.Actor("Car", "/Game/Maps/Showroom", [])
    key = U.Actor("KeyLight", "/Game/Maps/Showroom", [M.MOVABLE])
    fills = [U.Actor("Fill{}".format(i), "/Game/Maps/Showroom", [M.MOVABLE]) for i in range(10)]
    fills[0].comps[0].props["attenuation_radius"] = 8000.0
    fog = U.Actor("Fog", "/Game/Maps/Showroom", [])
    fog.others = [U.ExponentialHeightFogComponent(fog, True)]
    sky = U.Actor("Sky", "/Game/Maps/Showroom", [])
    sky.comps = [U.SkyLightComponent(sky, M.MOVABLE)]
    S.maps = {"/Game/Maps/Showroom": {"actors": [car, key, fog, sky] + fills}}
    U.LevelEditorSubsystem().load_level("/Game/Maps/Showroom")
    po.startup()
    return key, fills, fog, sky


def state():
    with open(po._state_file()) as f:
        return json.load(f)


def item(st, item_id):
    for c in st["categories"]:
        for it in c["items"]:
            if it["id"] == item_id:
                return it
    raise KeyError(item_id)


def frame_time():
    """Fake GPU cost that reacts to settings, to exercise the measurement."""
    ms = 20.0
    if U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] >= 32:
        ms -= 2.0
    if U.CVARS["r.Shadow.Virtual.ResolutionLodBiasLocal"] >= 1:
        ms -= 1.0
    if U.CVARS["t.MaxFPS"] > 0:
        ms = max(ms, 1000.0 / U.CVARS["t.MaxFPS"])
    return ms / 1000.0


def run_ticks(max_seconds=200):
    t = 0.0
    while po._busy and t < max_seconds:
        dt = frame_time()
        for cb in U.TICKS:
            cb(dt)
        t += dt
    assert not po._busy, "measurement did not finish"


def ini_text():
    with open(os.path.join(U.CONFIG, "DefaultEngine.ini"), newline="") as f:
        return f.read()


# ---- 1. Texture guard: texture cvars can't be part of the tool ----
try:
    po._CvarItem("x", "c", "n", "d", "None", "Low", "r.Streaming.PoolSize", 1)
    raise AssertionError("texture cvar accepted")
except ValueError:
    pass
try:
    po._cvar_set("r.MipMapLODBias", 1)
    raise AssertionError("texture cvar set")
except RuntimeError:
    pass
for it in po.ITEMS:
    if isinstance(it, po._CvarItem):
        assert not po.TEXTURE_CVAR_DENYLIST.match(it.cvar), it.cvar
print("texture guard OK")

# ---- 2. Scan ----
key, fills, fog, sky = reset()
po.ui_scan()
st = state()
assert not st["busy"] and st["categories"]
assert item(st, "lumen_gi_probes")["status"] == "suggest" and not item(st, "lumen_gi_probes")["enabled"]
assert item(st, "vsm_cache")["status"] == "ok" and item(st, "vsm_cache")["enabled"]
assert item(st, "rt_shadows_off")["status"] == "na"                     # RT off
assert item(st, "megalights")["status"] == "na"                         # 5.4 < 5.5
assert item(st, "skylight_realtime")["status"] == "suggest"             # sky uses real-time capture
assert item(st, "volumetric_shadow_off")["status"] == "suggest"
assert item(st, "shadowed_lights")["status"] == "suggest" and item(st, "shadowed_lights")["can_select"]
assert item(st, "attenuation")["status"] == "suggest"
assert item(st, "texture_guard")["status"] == "ok"
assert item(st, "screen_percentage")["visual_risk"] == "High"
assert item(st, "screen_percentage")["textures"] != "Not affected"
print("scan OK:", st["status_text"])

# ---- 3. Toggle on/off is session-only and exact ----
po.ui_set("lumen_gi_probes", True)
assert U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] == 32
st = state()
assert item(st, "lumen_gi_probes")["enabled"] and item(st, "lumen_gi_probes")["unsaved"]
assert ini_text() == INI, "toggling must not write the project config"
po.ui_set("lumen_gi_probes", False)
assert U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] == 16
assert not item(state(), "lumen_gi_probes")["unsaved"]
# Already-optimal setting that the tool didn't set can't be "reverted" by the tool
po.ui_set("vsm_cache", False)
assert U.CVARS["r.Shadow.Virtual.Cache"] == 1 and "NOT changed" in state()["status_text"]
# Read-only cvar: reported, not claimed as applied
U.READ_ONLY.add("r.LensFlareQuality")
po.ui_set("lens_flare_off", True)
assert "NOT changed" in state()["status_text"] and not item(state(), "lens_flare_off")["enabled"]
U.READ_ONLY.clear()
po._session["cvars"].pop("lens_flare_off", None)
print("toggles OK")

# ---- 4. Auto optimize, no visual impact only ----
before_cvars = dict(U.CVARS)
po.ui_auto_start(viewport_realtime=True, include_low=False, ask=False)
assert po._busy
run_ticks()
st = state()
assert U.CVARS["t.MaxFPS"] == 60 and U.CVARS["r.VSync"] == 0     # None-risk items
assert U.CVARS["r.VSyncEditor"] == 1, "measurement must restore editor vsync"
assert U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] == 16, "Low-risk item applied without consent"
assert U.CVARS["r.MotionBlurQuality"] == 4
assert all(U.CVARS[k] == before_cvars[k] for k in TEXTURE_KEYS)
assert ini_text() == INI
assert abs(po._results["change_pct"]) < 1.0, po._results  # pacing items aren't in the numbers
print("auto (none):", st["results_text"].splitlines()[0])

# ---- 5. Auto optimize including Low impact shows the gain ----
po.ui_auto_start(viewport_realtime=True, include_low=True, ask=False)
run_ticks()
st = state()
r = po._results
assert U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] == 32
assert U.CVARS["r.Shadow.Virtual.ResolutionLodBiasLocal"] == 1
assert U.CVARS["r.ScreenPercentage"] == 100, "screen percentage (High) must never be auto"
assert U.CVARS["t.MaxFPS"] == 60
assert r["change_pct"] > 15, r
assert all(U.CVARS[k] == before_cvars[k] for k in TEXTURE_KEYS)
assert os.path.exists(po._last_report)
print("auto (low):", st["results_text"].splitlines()[0])

# ---- 6. Preflight checks ----
po.ui_auto_start(viewport_realtime=False, include_low=True, ask=False)
assert not po._busy and "Realtime" in state()["status_text"]
S.pie = True
po.ui_measure(viewport_realtime=True)
assert not po._busy and "Play-In-Editor" in state()["status_text"]
S.pie = False

# ---- 7. Save to project, then revert + save restores the file exactly ----
po.ui_save_project()
text = ini_text()
assert "\r\n" in text
assert "; [PerformanceOptimizer] cvar=r.Lumen.ScreenProbeGather.DownsampleFactor runtime_before=16 " \
       "ini_before=r.Lumen.ScreenProbeGather.DownsampleFactor=24" in text, text
assert "t.MaxFPS=60" in text and "r.SomethingElse=1" in text
assert "GameDefaultMap=/Game/Maps/Showroom" in text
sys_section = text.split("[SystemSettings]")[1].split("[/Script/EngineSettings")[0]
assert "t.MaxFPS=60" in sys_section, "settings must go into [SystemSettings]"
assert not item(state(), "lumen_gi_probes")["unsaved"]
assert os.listdir(os.path.join(po._data_dir(), "Backups"))
# After an editor restart the session is empty, but the ini markers still allow a clean revert
po.startup()
po.ui_revert_all()
assert U.CVARS["r.Lumen.ScreenProbeGather.DownsampleFactor"] == 16
assert U.CVARS["t.MaxFPS"] == 0 and U.CVARS["r.VSync"] == 1
assert item(state(), "lumen_gi_probes")["unsaved"]
po.ui_save_project()
assert ini_text() == INI, "removing the settings must restore the original file:\n" + ini_text()
print("save/revert OK")

# ---- 8. Read-only config (local mode) is never overwritten ----
po.ui_set("motion_blur_off", True)
os.chmod(os.path.join(U.CONFIG, "DefaultEngine.ini"), stat.S_IREAD)
po.ui_save_project()
assert ini_text() == INI and "NOT saved" in state()["status_text"]
os.chmod(os.path.join(U.CONFIG, "DefaultEngine.ini"), stat.S_IREAD | stat.S_IWRITE)
po.ui_set("motion_blur_off", False)

# ---- 9. Level item: volumetric shadows, verified + reversible ----
lights = [key.comps[0]] + [f.comps[0] for f in fills]
po.ui_set("volumetric_shadow_off", True)
assert all(l.props["cast_volumetric_shadow"] is False for l in lights)
assert all(l.props["cast_shadows"] is True for l in lights), "normal shadows must stay"
assert item(state(), "volumetric_shadow_off")["enabled"]
po.ui_set("volumetric_shadow_off", False)
assert all(l.props["cast_volumetric_shadow"] is True for l in lights)
assert all(not any(str(t).startswith("PerfOptimizer.") for t in l.props["component_tags"]) for l in lights)
# a side effect (something moves) -> undone
orig_set = U.SceneComponent.set_editor_property


def set_with_side_effect(self, k, v):
    orig_set(self, k, v)
    if k == "cast_volumetric_shadow" and self is key.comps[0]:
        key.loc[0] += 50.0


U.SceneComponent.set_editor_property = set_with_side_effect
po.ui_set("volumetric_shadow_off", True)
U.SceneComponent.set_editor_property = orig_set
assert key.loc == [0.0, 0.0, 0.0] and all(l.props["cast_volumetric_shadow"] is True for l in lights)
assert "Safety check failed" in state()["status_text"]
print("level item OK")

# ---- 10. Select in level ----
po.ui_select("shadowed_lights")
assert len(S.selected) == 11, len(S.selected)
po.ui_select("attenuation")
assert [a.label for a in S.selected] == ["Fill0"]

# ---- 11. Texture guard warns about existing bad settings, never changes them ----
U.CVARS["r.Streaming.MipBias"] = 1
po.ui_scan()
tg = item(state(), "texture_guard")
assert tg["status"] == "warn" and "MipBias" in tg["suggestion"]
assert U.CVARS["r.Streaming.MipBias"] == 1
# ---- 12. An error right after starting a measurement doesn't leave the tab stuck ----
orig_uncap = po._uncap
po._uncap = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
po.ui_measure(viewport_realtime=True)
po._uncap = orig_uncap
assert not po._busy and "boom" in state()["status_text"] and not state()["busy"]
print("ALL PERF TESTS PASSED")
