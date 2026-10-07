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

# Not connected -> refuses
S.sc = False
r = lmt.process_all_maps(True, show_report=False)
assert r.errors and r.maps_done == 0 and a.comps[0].props["mobility"] == M.STATIONARY
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
print("ALL TESTS PASSED")
