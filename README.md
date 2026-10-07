# Light Mobility Tool (Unreal Engine 5 editor plugin)

Adds a checkbox to the editor: **Tools → Force Lights Movable (All Maps)**.

- **On:** after you confirm, the tool opens **every map in the project** (everything under `/Game`) one at a time.
  In each map it sets every light to **Movable**, so none are Static or Stationary, then saves the map.
  This covers Point, Spot, Rect, Directional and Sky lights, and also light components inside Blueprint actors.
  - Each light's original mobility is saved as a component tag (`LightMobilityTool.Original=Static`, for example).
  - **World Partition** maps are handled too. The tool loads their actors in batches of 500, so unloaded cells aren't skipped.
  - A progress bar with a **Cancel** button shows while it runs. When it finishes, it reopens the map you started on.
  - While the checkbox stays on, the open map is rescanned every 2 seconds, so lights you add later also become Movable.
- **Off:** opens every map again, sets each light back to its original mobility, removes the tag and saves the map.
- Before switching maps, the tool asks whether to save any unsaved work.
- The on/off state is saved in `Saved/LightMobilityTool.json` and persists across editor restarts.
- The tool doesn't change anything while Play-In-Editor is running.

## Perforce safety

- **Connection required:** the all-maps pass refuses to start unless the editor is connected to Perforce.
- **Skipped maps:** maps that aren't at the latest revision, or are checked out by someone else, are skipped entirely and listed in the report.
- **Checkout first:** a light is changed only after its file has been checked out. That's the `.umap`, or the actor's own file in `__ExternalActors__` for World Partition. If the checkout fails, the light is left alone.
- **No forced saves:** files that can't be checked out are never saved, and read-only files are never overwritten.
- **No submits:** nothing is submitted. Changes go to your default changelist, so you can review and submit them in P4V.
- **Report:** every run writes a report to `Saved/Logs/LightMobilityTool_<date>.txt` listing every change and skip.
- **Preview:** **Tools → Light Mobility: Preview (no changes)** shows what would change without touching any file.

## Install

See **[INSTALL.md](INSTALL.md)** for the full step-by-step guide, including adding the plugin to Perforce and a safe first run.

Short version:
1. Copy the `LightMobilityTool` folder to `YourProject/Plugins/LightMobilityTool/`.
2. Restart the editor and accept enabling the plugin.
3. Connect to Perforce in the editor, then run **Tools → Light Mobility: Preview (no changes)**.
4. Then run **Tools → Force Lights Movable (All Maps)**.

## Use from Python or the console

In the Output Log, switch the input from `Cmd` to `Python`:

```python
import light_mobility_tool as lmt
lmt.enable()                      # all maps: force lights Movable (asks first)
lmt.disable()                     # all maps: restore originals
lmt.enable(all_maps=False)        # only the open level
lmt.process_all_maps(make_movable=True)   # one-shot over all maps, no toggle
lmt.find_all_maps()               # list the maps it will touch
lmt.make_all_lights_movable()     # one-shot, open level only
```

From a Blueprint (an Editor Utility Widget button, for example), use the **Execute Python Command** node with
`import light_mobility_tool as lmt; lmt.toggle()`.

## Settings

These are at the top of `Content/Python/light_mobility_tool.py`:

- `MAP_ROOTS = ["/Game"]`: the folders searched for maps. Add `"/YourPlugin"` to include maps inside plugins,
  or narrow it to something like `["/Game/Maps"]`.
- `WP_ACTOR_BATCH_SIZE = 500`: how many World Partition actors are loaded at once. Lower it if memory runs out.
- `RESCAN_INTERVAL = 2.0`: how often, in seconds, the open map is rescanned while the tool is on.

## Pure-Blueprint alternative (no Python)

If you'd rather build it as an Editor Utility Blueprint:

1. Create a new **Editor Utility Widget**: *Content Browser → right-click → Editor Utilities → Editor Utility Widget*.
2. Add a **CheckBox** and bind **On Check State Changed (Is Checked)**.
3. In the graph, call **Get All Level Actors** (Editor Actor Subsystem) and loop over the results with a **For Each Loop**.
   - On each actor, call **Get Components By Class** with `LightComponentBase`, and loop over those components.
   - **If checked:** if the component's mobility isn't Movable, call **Component Tags → Add** with `Orig_Static` or `Orig_Stationary`, then call **Set Mobility (Movable)**.
   - **If unchecked:** if the component has `Orig_Static` or `Orig_Stationary` in its tags, call **Set Mobility** with that value and remove the tag.
4. Right-click the widget and choose **Run Editor Utility Widget**.

That only covers the open level. The Python plugin also goes through every map and handles World Partition, the auto-rescan and the saved state.

## Notes

- Movable lights skip baked lighting entirely, so they cost more at runtime. If your project uses Lumen,
  lighting is effectively dynamic already and this mostly removes the "lighting needs rebuild" workflow.
- Lights created by a Blueprint **Construction Script** get rebuilt when that script reruns, so they go back
  to whatever the script sets. The rescan switches them back to Movable on its next pass.
- The tool saves maps automatically. If you use source control (Perforce or Git LFS locking), check out the maps first,
  or the saves will fail; any failures show up in the Output Log.
- On a large project, going through every map can take a while. Commit or back up first, and test on a copy before running it.

## Tests

`python3 tests/test_tool.py` runs the tool's logic against a fake `unreal` module. It covers:
- preview mode, and refusing to run when disconnected from Perforce
- skipping maps that are locked or out of date
- per-actor World Partition checkouts
- that no file is saved without being checked out
- restoring the original mobility

It doesn't replace a test run inside the real editor.
