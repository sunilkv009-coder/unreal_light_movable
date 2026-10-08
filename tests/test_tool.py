"""Logic tests using a fake `unreal` module. Run: python3 tests/test_tool.py
These check the tool's decisions (what is changed, checked out, saved or skipped);
they do not replace a test inside the real editor."""
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "..", "LightMobilityTool", "Content", "Python"))
import unreal as U
import light_mobility_tool as lmt
M = U.ComponentMobility
S = U.STATE

def setup():
    S.checkouts = []; S.saved = []; S.files = {}; S.sc = True
    a = U.Actor("SunA", "/Game/Maps/A", [M.STATIONARY])
    a2 = U.Actor("LampA", "/Game/Maps/A", [M.STATIC, M.MOVABLE])
    sub = U.Actor("SubLevelLamp", "/Game/Maps/Sub", [M.STATIC])   # streamed sub-level actor
    b = U.Actor("LampB", "/Game/Maps/B", [M.STATIC])
    c = U.Actor("LampC", "/Game/Maps/C", [M.STATIC])
    wp_init = U.Actor("WPInit", "/Game/__ExternalActors__/Maps/W/0/AA", [M.STATIONARY])
    wp1 = U.Actor("WP1", "/Game/__ExternalActors__/Maps/W/1/BB", [M.STATIC])
    wp2 = U.Actor("WP2", "/Game/__ExternalActors__/Maps/W/2/CC", [M.STATIC])
    S.maps = {
        "/Game/Maps/A": {"actors": [a, a2, sub]},
        "/Game/Maps/Sub": {"actors": [sub]},
        "/Game/Maps/B": {"actors": [b]},           # locked by someone else
        "/Game/Maps/C": {"actors": [c]},           # out of date
        "/Game/Maps/W": {"actors": [wp_init], "wp": {"g1": wp1, "g2": wp2}},
    }
    S.files["/Game/Maps/B"] = U.FState(is_checked_out_other=True, checked_out_other="bob")
    S.files["/Game/Maps/C"] = U.FState(is_current=False)
    S.world = U.World("/Game/Maps/A"); S.loaded = []
    return a, a2, sub, b, c, wp_init, wp1, wp2

a, a2, sub, b, c, wpi, wp1, wp2 = setup()
lmt.WP_ACTOR_BATCH_SIZE = 1

# Preview changes nothing
r = lmt.process_all_maps(True, dry_run=True, show_report=False)
assert not S.checkouts and not S.saved, (S.checkouts, S.saved)
assert a.comps[0].props["mobility"] == M.STATIONARY
assert r.lights_changed == 6, r.lights_changed
print("preview: would change", r.lights_changed, "skipped maps", r.maps_skipped)

# Not connected + REQUIRE_SOURCE_CONTROL -> refuses
S.sc = False
lmt.REQUIRE_SOURCE_CONTROL = True
r = lmt.process_all_maps(True, show_report=False)
assert r.errors and r.maps_done == 0 and a.comps[0].props["mobility"] == M.STATIONARY
lmt.REQUIRE_SOURCE_CONTROL = False
S.sc = True

# Enable
lmt.enable()
assert a.comps[0].props["mobility"] == M.MOVABLE and a2.comps[0].props["mobility"] == M.MOVABLE
assert "LightMobilityTool.Original=STATIONARY" in a.comps[0].props["component_tags"]
assert sub.comps[0].props["mobility"] == M.MOVABLE
assert b.comps[0].props["mobility"] == M.STATIC, "locked map must be untouched"
assert c.comps[0].props["mobility"] == M.STATIC, "out-of-date map must be untouched"
for x in (wpi, wp1, wp2): assert x.comps[0].props["mobility"] == M.MOVABLE
assert "/Game/Maps/B" not in S.checkouts and "/Game/Maps/C" not in S.checkouts
print("checkouts:", S.checkouts)
print("saved:", S.saved)
assert set(S.saved) == {"/Game/Maps/A", "/Game/Maps/Sub", "/Game/__ExternalActors__/Maps/W/0/AA",
                        "/Game/__ExternalActors__/Maps/W/1/BB", "/Game/__ExternalActors__/Maps/W/2/CC"}
assert S.saved.count("/Game/Maps/Sub") == 1
print("dialog:\n", U.DIALOGS[-1])

# Disable restores
S.checkouts = []; S.saved = []
for f in list(S.files): 
    if f not in ("/Game/Maps/B", "/Game/Maps/C"): S.files[f].d["is_checked_out"] = False  # "submitted"
lmt.disable()
assert a.comps[0].props["mobility"] == M.STATIONARY and a2.comps[0].props["mobility"] == M.STATIC
assert a2.comps[1].props["mobility"] == M.MOVABLE, "originally movable stays"
assert a.comps[0].props["component_tags"] == []
for x, m in ((wpi, M.STATIONARY), (wp1, M.STATIC), (wp2, M.STATIC)): assert x.comps[0].props["mobility"] == m
print("restore OK, saved:", S.saved)

# Light in a file that can't be checked out is not changed
a, a2, sub, b, c, wpi, wp1, wp2 = setup()
S.files["/Game/__ExternalActors__/Maps/W/1/BB"] = U.FState(is_checked_out_other=True, checked_out_other="amy")
r = lmt.process_all_maps(True, show_report=False)
assert wp1.comps[0].props["mobility"] == M.STATIC and wp2.comps[0].props["mobility"] == M.MOVABLE
print("skipped lights:", r.lights_skipped)
# Local mode (no source control): writable maps saved directly, read-only skipped
import os, stat
a, a2, sub, b, c, wpi, wp1, wp2 = setup()
S.sc = False
os.makedirs(os.path.join(U.CONTENT, "Maps"), exist_ok=True)
for name in ("A", "Sub", "B", "C", "W"):
    path = os.path.join(U.CONTENT, "Maps", name + ".umap")
    if os.path.exists(path): os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    open(path, "w").close()
ro = os.path.join(U.CONTENT, "Maps", "B.umap")
os.chmod(ro, stat.S_IREAD)
assert not lmt.source_control_enabled()
r = lmt.process_all_maps(True, show_report=False)
assert not r.errors, r.errors
assert a.comps[0].props["mobility"] == M.MOVABLE
assert c.comps[0].props["mobility"] == M.MOVABLE, "local mode: no out-of-date concept"
assert b.comps[0].props["mobility"] == M.STATIC, "read-only file must be left alone"
assert any("read-only" in reason for _, reason in r.maps_skipped), r.maps_skipped
assert not S.checkouts
assert "/Game/Maps/B" not in S.saved and "/Game/Maps/C" in S.saved
print("local mode: changed", r.lights_changed, "skipped", r.maps_skipped)
lmt.disable(ask=False)
assert a.comps[0].props["mobility"] == M.STATIONARY and c.comps[0].props["mobility"] == M.STATIC
print("local mode restore OK")
os.chmod(ro, stat.S_IWRITE | stat.S_IREAD)
S.sc = True
# ---- Safety: nothing may move / change besides mobility ----
lmt._blocked.clear()
a, a2, sub, b, c, wpi, wp1, wp2 = setup()
S.maps.pop("/Game/Maps/B"); S.maps.pop("/Game/Maps/C")
# Headlight: changing mobility triggers a construction-script-like move
head = U.Actor("Headlight_BP", "/Game/Maps/Car", [M.STATIC])
# Light with a static mesh attached: must be skipped
lamp_mesh = U.Actor("LampWithMesh", "/Game/Maps/Car", [M.STATIC])
U.SceneComponent(lamp_mesh, M.STATIC, "LampShadeMesh", parent=lamp_mesh.comps[0])
lamp_mesh.others = lamp_mesh.comps[0].children
# Light with an editor-only static helper (arrow/billboard): must NOT be skipped
lamp_helper = U.Actor("SunWithArrow", "/Game/Maps/Car", [M.STATIONARY])
U.SceneComponent(lamp_helper, M.STATIC, "ArrowComponent", parent=lamp_helper.comps[0], editor_only=True)
S.maps["/Game/Maps/Car"] = {"actors": [head, lamp_mesh, lamp_helper]}
S.maps["/Game/Maps/Car2"] = {"actors": [U.Actor("Fill", "/Game/Maps/Car2", [M.STATIC])]}
def side_effect(comp):
    if comp.owner is head: head.loc[0] += 5.0
U.SIDE_EFFECT[0] = side_effect
r = lmt.process_all_maps(True, show_report=False)
U.SIDE_EFFECT[0] = None
assert head.loc == [0.0, 0.0, 0.0], head.loc
assert head.comps[0].props["mobility"] == M.STATIC and head.comps[0].props["component_tags"] == []
assert lamp_mesh.comps[0].props["mobility"] == M.STATIC
assert lamp_mesh.others[0].props["mobility"] == M.STATIC
assert lamp_helper.comps[0].props["mobility"] == M.MOVABLE, "retried alone and passed"
assert "/Game/Maps/Car" not in S.saved, "map with a failed safety check must not be saved"
assert "/Game/Maps/Car2" in S.saved, "other maps still processed"
assert any("SAFETY CHECK" in e for e in r.errors), r.errors
assert any("LampWithMesh" in n for n, _ in r.lights_skipped), r.lights_skipped
print("safety errors:", r.errors)
print("safety skips:", r.lights_skipped)

# World Partition: only the offending actor's own file is left unsaved
lmt._blocked.clear(); S.saved = []
good = U.Actor("WPGood", "/Game/__ExternalActors__/Maps/Car4/0/G", [M.STATIC])
bad = U.Actor("WPBad", "/Game/__ExternalActors__/Maps/Car4/1/B", [M.STATIC])
S.maps["/Game/Maps/Car4"] = {"actors": [good, bad]}
U.SIDE_EFFECT[0] = lambda comp: bad.loc.__setitem__(2, 10.0) if comp.owner is bad else None
r = lmt.process_all_maps(True, maps=["/Game/Maps/Car4"], show_report=False)
U.SIDE_EFFECT[0] = None
assert good.comps[0].props["mobility"] == M.MOVABLE and bad.comps[0].props["mobility"] == M.STATIC
assert bad.loc == [0.0, 0.0, 0.0]
assert S.saved == ["/Game/__ExternalActors__/Maps/Car4/0/G"], S.saved

# Without the side effect, the helper-only light is changed and the map saved
lmt._blocked.clear(); S.saved = []
r = lmt.process_all_maps(True, maps=["/Game/Maps/Car"], show_report=False)
assert head.comps[0].props["mobility"] == M.MOVABLE and lamp_helper.comps[0].props["mobility"] == M.MOVABLE
assert lamp_mesh.comps[0].props["mobility"] == M.STATIC
assert "/Game/Maps/Car" in S.saved and not r.errors

# A light setting changed by side effect is also caught
lmt._blocked.clear(); S.saved = []
x = U.Actor("Spot", "/Game/Maps/Car3", [M.STATIC])
S.maps["/Game/Maps/Car3"] = {"actors": [x]}
U.SIDE_EFFECT[0] = lambda comp: comp.props.__setitem__("intensity", 99.0)
r = lmt.process_all_maps(True, maps=["/Game/Maps/Car3"], show_report=False)
U.SIDE_EFFECT[0] = None
assert x.comps[0].props["mobility"] == M.STATIC and "/Game/Maps/Car3" not in S.saved
assert any("intensity" in e for e in r.errors), r.errors
# ---- Directional light (sun) ----
lmt._blocked.clear(); S.saved = []
sun = U.Actor("DirectionalLight", "/Game/Maps/Sun", [])
sun.comps = [U.DirectionalLightComponent(sun, M.STATIONARY)]
sun.pitch, sun.yaw = -90.0, 30.0
# Its arrow is a static, non-flagged helper: must not block the light
U.ArrowComponent(sun, M.STATIC, "ArrowComponent0", parent=sun.comps[0])
sun.others = list(sun.comps[0].children)
S.maps["/Game/Maps/Sun"] = {"actors": [sun]}
# Re-registering at pitch -90 returns the SAME orientation as different euler numbers
def euler_flip(comp):
    if comp.owner is sun and sun.pitch == -90.0 and sun.yaw == 30.0:
        sun.roll, sun.yaw = 30.0, 0.0
U.SIDE_EFFECT[0] = euler_flip
r = lmt.process_all_maps(True, maps=["/Game/Maps/Sun"], show_report=False)
U.SIDE_EFFECT[0] = None
assert sun.comps[0].props["mobility"] == M.MOVABLE, (r.errors, r.lights_skipped)
assert not r.errors and not r.lights_skipped
assert "/Game/Maps/Sun" in S.saved
# A real rotation of the sun is still caught
lmt._blocked.clear(); S.saved = []
sun.comps[0].props["mobility"] = M.STATIONARY; sun.comps[0].props["component_tags"] = []
sun.pitch, sun.yaw, sun.roll = -45.0, 30.0, 0.0
U.SIDE_EFFECT[0] = lambda comp: setattr(sun, "yaw", 31.0) if comp.owner is sun else None
r = lmt.process_all_maps(True, maps=["/Game/Maps/Sun"], show_report=False)
U.SIDE_EFFECT[0] = None
assert sun.comps[0].props["mobility"] == M.STATIONARY and any("rotated" in e for e in r.errors), r.errors
print("directional light OK")

# ---- Unsaved work is never thrown away (the lost Rect Light case) ----
lmt._blocked.clear(); S.saved = []
rect_map = "/Game/Maps/Rect"
existing = U.Actor("ExistingLight", rect_map, [M.STATIC])
S.maps[rect_map] = {"actors": [existing]}
S.maps["/Game/Maps/Other"] = {"actors": [U.Actor("OtherLight", "/Game/Maps/Other", [M.STATIC])]}
U.LevelEditorSubsystem().load_level(rect_map)
new_rect = U.Actor("RectLight", rect_map, [M.STATIC])   # placed, not saved yet
S.loaded.append(new_rect)
U.DIRTY.add(rect_map)                                   # user clicked "Don't Save"
loads = []
orig_load = U.LevelEditorSubsystem.load_level
U.LevelEditorSubsystem.load_level = lambda self, p: (loads.append(p), orig_load(self, p))[1]
r = lmt.process_all_maps(True, maps=[rect_map, "/Game/Maps/Other"], show_report=False)
U.LevelEditorSubsystem.load_level = orig_load
assert not loads, "must not switch maps while something is unsaved"
assert new_rect in S.loaded and new_rect.comps[0].props["mobility"] == M.STATIC
assert r.errors and "unsaved" in r.errors[0] and r.maps_done == 0
U.DIRTY.clear()
print("unsaved guard OK")

# ---- Every run goes through every map again; nothing remembered ----
lmt._blocked.clear(); S.saved = []
a1 = U.Actor("L1", "/Game/Maps/R1", [M.STATIC])
a2 = U.Actor("L2", "/Game/Maps/R2", [M.STATIONARY])
S.maps["/Game/Maps/R1"] = {"actors": [a1]}
S.maps["/Game/Maps/R2"] = {"actors": [a2]}
U.SIDE_EFFECT[0] = lambda comp: a2.loc.__setitem__(0, 9.0) if comp.owner is a2 else None
r1 = lmt.process_all_maps(True, maps=["/Game/Maps/R1", "/Game/Maps/R2"], show_report=False)
U.SIDE_EFFECT[0] = None
a2.loc = [0.0, 0.0, 0.0]
assert a1.comps[0].props["mobility"] == M.MOVABLE and a2.comps[0].props["mobility"] == M.STATIONARY
r2 = lmt.process_all_maps(True, maps=["/Game/Maps/R1", "/Game/Maps/R2"], show_report=False)
assert r2.maps_done == 2 and not r2.maps_skipped, "second run must process every map"
assert a2.comps[0].props["mobility"] == M.MOVABLE, "light skipped in run 1 must be retried in run 2"
assert len(r2.already_movable) == 1   # L1 from the first run
print("rerun OK")

# ---- No background watcher, no on/off memory ----
old_state = os.path.join(U.SAVED, "LightMobilityTool.json")
open(old_state, "w").write('{"enabled": true}')
ticks_before = len(U.TICKS)
lmt.startup()
assert len(U.TICKS) == ticks_before, "startup must not start anything in the background"
assert not os.path.exists(old_state), "old on/off memory must be removed"
assert not hasattr(lmt, "toggle") and not hasattr(lmt, "is_enabled")
print("no memory OK")

# ---- The user's project: lights in sublevels outside /Game, main map out of date ----
lmt._blocked.clear(); S.saved = []; S.files = {}; S.sc = True; S.checkouts = []
U.DIALOGS.clear()
main, ph = "/Game/Maps/RoD_MAIN", "/RoDContent/S_Placeholder"
sun = U.Actor("DirectionalLight", ph, [])
sun.comps = [U.DirectionalLightComponent(sun, M.STATIC)]
U.ArrowComponent(sun, M.STATIC, "ArrowComponent0", parent=sun.comps[0])
sun.others = list(sun.comps[0].children)
spot = U.Actor("SpotLight", ph, [M.STATIC])
main_light = U.Actor("MainFill", main, [M.STATIC])
S.maps = {
    "/Game/Maps/CAM_CINECAM": {"actors": []},
    "/Game/Maps/CAM_ORBIT": {"actors": []},
    main: {"actors": [main_light, sun, spot], "sublevels": ["/Game/Maps/CAM_CINECAM", ph]},
    ph: {"actors": [sun, spot]},
}
S.files[main] = U.FState(is_current=False)
assert lmt.find_all_maps() == ["/Game/Maps/CAM_CINECAM", "/Game/Maps/CAM_ORBIT", main]
warning = lmt._skip_warning(lmt.find_all_maps())
assert "will be SKIPPED" in warning and main in warning, warning
r = lmt.process_all_maps(True, maps=lmt.find_all_maps(), show_report=False)
assert sun.comps[0].props["mobility"] == M.MOVABLE, "directional light in the sublevel must change"
assert spot.comps[0].props["mobility"] == M.MOVABLE, "spot light in the sublevel must change"
assert main_light.comps[0].props["mobility"] == M.STATIC, "out-of-date map must not be edited"
assert ph in S.saved and main not in S.saved
assert [m for m, _ in r.maps_skipped] == [main] and r.lights_not_changed == 1
text = r.text()
assert "NOT changed (map skipped): MainFill" in text and "+ sublevel /RoDContent/S_Placeholder" in text
assert "2 light(s) in this map (0 Movable, 0 Stationary, 2 Static)" in text
print("sublevel discovery OK")
print(text.split("DETAILS")[1])
print("ALL TESTS PASSED")
