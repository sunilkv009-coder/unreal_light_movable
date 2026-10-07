# Light Mobility Tool (Unreal Engine 5 editor plugin)

Adds a checkbox to the editor: **Tools → Force Lights Movable**.

- **On:** sets every light in the open level to **Movable**, so none are Static or Stationary.
  This covers Point, Spot, Rect, Directional and Sky lights, and also light components inside Blueprint actors.
  Each light's original mobility is saved as a component tag (`LightMobilityTool.Original=Static`, for example).
  While the checkbox is on, the tool rescans every 2 seconds, so lights you add later and lights in levels you open also become Movable.
- **Off:** sets each light the tool changed back to its original mobility and removes the tag.
- Each batch is one undo step, so **Ctrl+Z** reverts it.
- The on/off state is saved in `Saved/LightMobilityTool.json` and persists across editor restarts.
- The tool doesn't change anything while Play-In-Editor is running.

## Install

1. Copy the `LightMobilityTool` folder into your project's `Plugins/` folder.
   Create `Plugins/` if it doesn't exist. The result is `YourProject/Plugins/LightMobilityTool/LightMobilityTool.uplugin`.
2. Restart the editor. The plugin turns on **Python Editor Script Plugin** and **Editor Scripting Utilities** automatically.
   If it asks, enable **Light Mobility Tool** under *Edit → Plugins*.
3. Open **Tools → Force Lights Movable** and click it to switch it on or off.

## Use from Python or the console

In the Output Log, switch the input from `Cmd` to `Python`:

```python
import light_mobility_tool as lmt
lmt.enable()      # force all lights Movable
lmt.disable()     # restore originals
lmt.toggle()
lmt.make_all_lights_movable()   # one-shot, does not turn on the watcher
```

From a Blueprint (an Editor Utility Widget button, for example), use the **Execute Python Command** node with
`import light_mobility_tool as lmt; lmt.toggle()`.

## Pure-Blueprint alternative (no Python)

If you'd rather build it as an Editor Utility Blueprint:

1. Create a new **Editor Utility Widget**: *Content Browser → right-click → Editor Utilities → Editor Utility Widget*.
2. Add a **CheckBox** and bind **On Check State Changed (Is Checked)**.
3. In the graph, call **Get All Level Actors** (Editor Actor Subsystem) and loop over the results with a **For Each Loop**.
   - On each actor, call **Get Components By Class** with `LightComponentBase`, and loop over those components.
   - **If checked:** if the component's mobility isn't Movable, call **Component Tags → Add** with `Orig_Static` or `Orig_Stationary`, then call **Set Mobility (Movable)**.
   - **If unchecked:** if the component has `Orig_Static` or `Orig_Stationary` in its tags, call **Set Mobility** with that value and remove the tag.
4. Right-click the widget and choose **Run Editor Utility Widget**.

The Python plugin above does the same thing, and also handles undo, the auto-rescan and the saved state.

## Notes

- Movable lights skip baked lighting entirely, so they cost more at runtime. If your project uses Lumen,
  lighting is effectively dynamic already and this mostly removes the "lighting needs rebuild" workflow.
- Lights created by a Blueprint **Construction Script** get rebuilt when that script reruns, so they go back
  to whatever the script sets. The rescan switches them back to Movable on its next pass.
- When you switch the tool off, only the currently open level is restored. Other levels keep their tags,
  and you can restore one by opening it and running `lmt.restore_original_mobility()`.
