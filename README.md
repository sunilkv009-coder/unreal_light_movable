# Light Mobility Tool + Performance Improvements (Unreal Engine 5 editor plugins)

This repository has two tools:

- **Light Mobility Tool:** makes every light in every map Movable, safely. It's described below.
- **Performance Improvements tab:** scans the project and level, gives per-setting toggles with suggestions,
  and runs an Auto Optimize with before/after FPS. Textures are never touched. See **[PERFORMANCE.md](PERFORMANCE.md)**.

---

Adds three commands to the **Tools** menu:

- **Lights: Make All Movable (All Maps)**
- **Lights: Restore Original Mobility (All Maps)**
- **Lights: Preview (no changes)**

Each command runs once and finishes. Nothing keeps running in the background, and nothing is remembered between runs or editor restarts.
Running a command again goes through every map again.

- **Make All Movable:** after you confirm, the tool opens **every map in the project** (everything under `/Game`) one at a time.
  In each map it sets every light to **Movable**, so none are Static or Stationary, then saves the map.
  This covers Point, Spot, Rect, Directional and Sky lights, and also light components inside Blueprint actors.
  - Each light's original mobility is saved as a component tag (`LightMobilityTool.Original=Static`, for example).
  - **World Partition** maps are handled too. The tool loads their actors in batches of 500, so unloaded cells aren't skipped.
  - A progress bar with a **Cancel** button shows while it runs. When it finishes, it reopens the map you started on.
  - **Sublevels are included wherever they're stored**, even outside `/Game`. The tool finds them from the maps that use them.
  - **Before it starts**, the tool warns you about maps it will have to skip (out of date or locked in Perforce), so you can Get Latest first.
  - **The report** lists every map with how many lights it has (Movable / Stationary / Static), each light it changed,
    the lights it could **not** change because their map was skipped, and anything else skipped with the reason.
  - Lights you add later aren't changed automatically. Run the command again.
- **Restore Original Mobility:** opens every map again, sets each light back to its original mobility, removes the tag and saves the map.
- **Unsaved work is protected.** Opening another map makes Unreal throw away unsaved changes without asking, so the tool asks you to save first.
  If anything is still unsaved after that, for example a light you just placed, **the run doesn't start** and nothing is changed.
- The tool doesn't change anything while Play-In-Editor is running.

## Production safety: nothing moves

The tool changes only one setting per light, **Mobility**, plus a tag that remembers the original value.
After every change it checks that nothing else changed:

1. **Before:** it records the position, rotation and scale of every actor in the level, plus every component of the affected actors and anything attached to them.
   It also records their attachments, the mobility of non-light components, and the light settings
   (intensity, color, temperature, attenuation, cone angles, source size, IES, light function, shadows, lighting channels and so on).
2. **After:** it compares everything against the recording, with tolerances of 0.001 cm, 0.001° and 0.00001 scale.
3. **If anything else changed**, for example a Blueprint construction script reacting to the change:
   - the change is undone and the positions are put back;
   - the tool retries the lights one at a time, so only the light that caused the problem is left alone;
   - the file that light lives in is **not saved**;
   - the problem is listed under ERRORS in the report.
4. **Lights with non-movable things attached**, such as a lamp-shade mesh under a spot light, are skipped and reported.
   Unreal could force those attached things to Movable as well. Editor helpers, like the arrow on a directional light and light icon sprites, are ignored.
   Lights driven by a sun/sky Blueprint (for example SunSky with its compass mesh) can be skipped for that reason, and the report names the attached part.
5. **Rotation check:** rotation is compared as an actual orientation, not as pitch/yaw/roll numbers, so a sun pointing straight down (−90° pitch) isn't mistaken for a rotated one.
6. **Saving:** only the files that contain lights the tool changed are saved. Anything else Unreal marks as modified when it opens a map is thrown away.

**What does change visually.** Moving a light from Static or Stationary to Movable changes how Unreal renders it:
baked lightmaps and shadow maps are no longer used, and shadows and GI become fully dynamic.
That's the purpose of the tool, but it can change the look:
- **Lumen / fully dynamic projects:** expect little or no difference.
- **Projects relying on baked lighting:** expect visible differences.

For automotive and pixel-streaming work, compare a few reference shots before and after,
using Preview first and then a test branch, before rolling it out.

## Works with or without source control

The tool checks whether the editor is connected to source control and picks a mode automatically:

| | **Source control mode** (Perforce connected) | **Local mode** (no source control, or not connected) |
|---|---|---|
| Saving | Checks out each file, then saves it | Saves straight to disk |
| Read-only files | Checked out first, or skipped if that fails | Skipped, never overwritten |
| Out-of-date / locked by others | Skipped | Not applicable |
| Submits | Never | Not applicable |

The confirm dialog tells you which mode it's about to use.
In local mode on a normal project, back up or commit your project first, because maps are saved directly.

Local mode is still safe on a Perforce project where you forgot to connect. Perforce keeps files read-only until
they're checked out, so the tool skips them instead of overwriting them, and the report tells you to connect.
To make Perforce mandatory, set `REQUIRE_SOURCE_CONTROL = True`.

## Perforce safety (source control mode)

- **Skipped maps:** maps that aren't at the latest revision, or are checked out by someone else, are skipped entirely and listed in the report.
- **Checkout first:** a light is changed only after its file has been checked out. That's the `.umap`, or the actor's own file in `__ExternalActors__` for World Partition. If the checkout fails, the light is left alone.
- **No forced saves:** files that can't be checked out are never saved, and read-only files are never overwritten.
- **No submits:** nothing is submitted. Changes go to your default changelist, so you can review and submit them in P4V.
- **Report:** every run, in either mode, writes a report to `Saved/Logs/LightMobilityTool_<date>.txt` listing every change and skip.
- **Preview:** **Tools → Lights: Preview (no changes)** shows what would change without touching any file.

## Install

See **[INSTALL.md](INSTALL.md)** for the full step-by-step guide, including adding the plugin to Perforce and a safe first run.

Short version:
1. Copy the `LightMobilityTool` folder to `YourProject/Plugins/LightMobilityTool/`.
2. Restart the editor and accept enabling the plugin.
3. On a Perforce project, connect to Perforce in the editor. On a normal project, back up first.
   Then run **Tools → Lights: Preview (no changes)**.
4. Then run **Tools → Lights: Make All Movable (All Maps)**.

## Use from Python or the console

In the Output Log, switch the input from `Cmd` to `Python`:

```python
import light_mobility_tool as lmt
lmt.run_make_movable()            # all maps: make lights Movable (asks first)
lmt.run_restore()                 # all maps: restore originals
lmt.preview_all_maps()            # all maps: report only
lmt.find_all_maps()               # list the maps it will touch
lmt.make_all_lights_movable()     # open level only (not saved for you)
```

From a Blueprint (an Editor Utility Widget button, for example), use the **Execute Python Command** node with
`import light_mobility_tool as lmt; lmt.run_make_movable()`.

## Settings

These are at the top of `Content/Python/light_mobility_tool.py`:

- `MAP_ROOTS = ["/Game"]`: the folders searched for maps. Add `"/YourPlugin"` to include maps inside plugins,
  or narrow it to something like `["/Game/Maps"]`.
- `WP_ACTOR_BATCH_SIZE = 500`: how many World Partition actors are loaded at once. Lower it if memory runs out.

## Pure-Blueprint alternative (no Python)

If you'd rather build it as an Editor Utility Blueprint:

1. Create a new **Editor Utility Widget**: *Content Browser → right-click → Editor Utilities → Editor Utility Widget*.
2. Add a **CheckBox** and bind **On Check State Changed (Is Checked)**.
3. In the graph, call **Get All Level Actors** (Editor Actor Subsystem) and loop over the results with a **For Each Loop**.
   - On each actor, call **Get Components By Class** with `LightComponentBase`, and loop over those components.
   - **If checked:** if the component's mobility isn't Movable, call **Component Tags → Add** with `Orig_Static` or `Orig_Stationary`, then call **Set Mobility (Movable)**.
   - **If unchecked:** if the component has `Orig_Static` or `Orig_Stationary` in its tags, call **Set Mobility** with that value and remove the tag.
4. Right-click the widget and choose **Run Editor Utility Widget**.

That only covers the open level. The Python plugin also goes through every map, handles World Partition and Perforce, and checks that nothing moves.

## Notes

- Movable lights skip baked lighting entirely, so they cost more at runtime. If your project uses Lumen,
  lighting is effectively dynamic already and this mostly removes the "lighting needs rebuild" workflow.
- Lights created by a Blueprint **Construction Script** get rebuilt when that script reruns, so they go back
  to whatever the script sets. To make them Movable for good, set Mobility inside the Blueprint itself.
- The tool saves maps automatically. If you use source control (Perforce or Git LFS locking), check out the maps first,
  or the saves will fail; any failures show up in the Output Log.
- On a large project, going through every map can take a while. Commit or back up first, and test on a copy before running it.

## Tests

`python3 tests/test_perf.py` tests the Performance Improvements logic:
- the texture deny list;
- scanning;
- session-only toggles;
- Auto Optimize at both impact levels, with measurement;
- Save to Project restoring `DefaultEngine.ini` byte for byte;
- read-only config files;
- the level toggle's safety check.

`python3 tests/test_tool.py` runs the tool's logic against a fake `unreal` module. It covers:
- preview mode, and refusing to run when disconnected from Perforce
- skipping maps that are locked or out of date
- per-actor World Partition checkouts
- that no file is saved without being checked out
- restoring the original mobility

It doesn't replace a test run inside the real editor.
