# Installation guide: Light Mobility Tool (Unreal Engine 5)

This guide gets the tool into your project and covers a safe first run. The tool works on any project:

- **With Perforce:** connect in the editor (step 6) and the tool checks files out before saving them.
- **Without source control:** the tool saves maps directly to disk ("local mode"). Back up your project first.

The Perforce-only steps are marked **(Perforce)**. Skip them on a normal project.

**Supported:** Unreal Engine 5.0 and later. 5.1+ is recommended, because World Partition support needs 5.1.
It works in Blueprint-only and C++ projects. You don't need to compile anything; it's a content-only plugin that uses Python.

---

## 1. Get the files

Download this repository from GitHub: **Code → Download ZIP**, then unzip it. The folder you need is `LightMobilityTool`:

```
LightMobilityTool/
├── LightMobilityTool.uplugin
└── Content/
    └── Python/
        ├── init_unreal.py
        └── light_mobility_tool.py
```

## 2. Copy it into your project

1. Close the Unreal Editor.
2. Open your project folder, the one that contains `YourProject.uproject`.
3. If there's no `Plugins` folder, create one.
4. Copy the whole `LightMobilityTool` folder into `Plugins`. The result must look like this:

```
YourProject/
├── YourProject.uproject
├── Content/
└── Plugins/
    └── LightMobilityTool/
        ├── LightMobilityTool.uplugin      <- must be directly inside this folder
        └── Content/Python/...
```

> Common mistake: unzipping creates `Plugins/LightMobilityTool/LightMobilityTool/...`, one folder too deep.
> The `.uplugin` file has to sit directly in `Plugins/LightMobilityTool/`.

## 3. (Perforce) Add it to Perforce, so the whole team gets it

Skip this step if you don't use Perforce, or only you need the tool.

1. In P4V, open your workspace and go to `YourProject/Plugins/LightMobilityTool`.
2. Right-click the folder and choose **Mark for Add...**. Add these 3 files to a new changelist named something like *"Add Light Mobility Tool plugin"*:
   - `LightMobilityTool.uplugin`
   - `Content/Python/init_unreal.py`
   - `Content/Python/light_mobility_tool.py`
3. Don't add any `__pycache__` folders or `.pyc` files. Python creates these, and they shouldn't be versioned.
   If your project has a `.p4ignore` file, add this line to it:
   ```
   __pycache__/
   ```
4. Submit the changelist. Teammates get the tool the next time they **Get Latest** and restart the editor.

## 4. Open the editor and enable the plugin

1. Open `YourProject.uproject`.
2. If Unreal asks whether to enable the new plugin or its dependencies, click **Yes**, and restart if it asks you to.
3. Check it's enabled: **Edit → Plugins**, then search for *Light Mobility*. The box should be ticked.
   The plugin also turns on two built-in Unreal plugins it needs:
   - **Python Editor Script Plugin**
   - **Editor Scripting Utilities**

   If either isn't ticked, tick it and restart the editor.

> If enabling the plugin changes your `.uproject` file, Unreal checks it out in Perforce. Submit that change too,
> so the plugin is enabled for everyone.

## 5. Check that it loaded

1. Open the **Tools** menu at the top of the editor. There should be a **Lighting** section with:
   - **Force Lights Movable (All Maps)**, a checkbox
   - **Light Mobility: Preview (no changes)**
2. Open **Window → Output Log** and type `LightMobilityTool` in its search box. There should be no red errors.

If the menu items are missing, see [Troubleshooting](#troubleshooting) below.

## 6. (Perforce) Connect to Perforce inside Unreal

**No source control?** Skip this step. Just make a backup copy of your project folder (or commit it, if you use Git)
before the first run.

On a Perforce project, always connect before running the tool. If you forget, the tool doesn't break anything:
Perforce keeps files read-only, so the tool skips them and the report tells you to connect. But it won't get
any work done either.

1. Click **Revision Control** (or **Source Control** in older versions), at the bottom-right of the editor.
2. Choose **Connect to Revision Control → Perforce**.
3. Enter your server, user and **workspace**. It must be the workspace this project lives in.
4. Click **Accept Settings**. The icon turns green when you're connected.

## 7. First run (do these in order)

1. **(Perforce)** **Get Latest** in P4V, so every map is at the latest revision. The tool skips maps that are out of date.
   **(No source control)** Back up your project folder.
2. **(Perforce)** Ask your team to check in, or at least release, any maps they have checked out. The tool skips maps someone else has locked.
3. Run **Tools → Light Mobility: Preview (no changes)**.
   - It opens every map and lists the lights it would change. It doesn't modify, check out or save anything.
   - When it finishes, it shows a summary and the path of a full report (`Saved/Logs/LightMobilityTool_<date>.txt`).
4. Read the report. If it looks right, click **Tools → Force Lights Movable (All Maps)**.
   The confirm dialog says which mode it will use, **source control** or **LOCAL MODE**. Check that's the mode you expect, then click **Yes**.
5. When it finishes, read the summary and the report. It lists every map and light that was skipped, and why.
   - Check the **ERRORS** section. A "SAFETY CHECK" entry means a light's change caused something else to change
     (usually a Blueprint construction script). The tool undid it and didn't save that file. Change that light by hand, or leave it.
   - Lights skipped with "non-movable things attached" need you to decide: make the attached mesh Movable as well, or leave the light as it is.
   - Compare a few reference shots or camera views before and after. Switching from baked to dynamic lighting can change the look.
6. **(No source control)** You're done. Open a couple of maps and check the lighting.
7. **(Perforce)** In P4V, open your **default changelist**:
   - It contains the maps the tool changed. For World Partition maps, it also contains the actor files in `__ExternalActors__`.
   - Open a couple of maps in the editor and check the lighting.
   - Then **Submit**. The tool never submits for you.

To undo everything, untick **Force Lights Movable (All Maps)**. It goes through every map again, puts each light back to its original Static or Stationary setting, checks out the files and saves them, ready for you to submit.
If you haven't submitted yet, you can also just **Revert** the changelist in P4V. Without source control, you can restore your backup.

## 8. What the tool will never do

- Move, rotate or scale anything, or change attachments. Every change is verified, and if anything moved, the change is undone and that file isn't saved.
- Change any light setting other than **Mobility**. Intensity, color, temperature, attenuation, IES, shadows and so on are verified to be identical afterwards.
- Change lights that have non-movable meshes attached to them. These are skipped and reported.
- Save files it didn't change itself.

- Save a file it couldn't check out. It never uses "make writable", and never overwrites a read-only file.
- Change a map, or an actor file, that someone else has checked out.
- Change a map that isn't at the latest revision.
- Submit to Perforce.
- Run while Play-In-Editor is active.
- Overwrite a read-only file in local mode.

## 9. Settings (optional)

These are at the top of `Plugins/LightMobilityTool/Content/Python/light_mobility_tool.py`:

| Setting | Default | Meaning |
|---|---|---|
| `MAP_ROOTS` | `["/Game"]` | Folders searched for maps. Use `["/Game/Maps"]` to narrow it, or add `"/MyPlugin"` to include plugin maps. |
| `REQUIRE_SOURCE_CONTROL` | `False` | `False` works on any project (local mode when not connected). Set it to `True` to refuse to run unless connected to Perforce. |
| `SKIP_FILES_CHECKED_OUT_BY_OTHERS` | `True` | Leave files locked by teammates alone. |
| `SKIP_OUT_OF_DATE_FILES` | `True` | Leave files that aren't at head revision alone. |
| `SKIP_LIGHTS_WITH_NON_MOVABLE_CHILDREN` | `True` | Skip lights that have non-movable meshes or components attached. |
| `POSITION_TOLERANCE` / `ROTATION_TOLERANCE` / `SCALE_TOLERANCE` | `0.001` cm / `0.001`° / `0.00001` | How much movement counts as "moved" in the safety check. |
| `LIGHT_PROPERTIES_TO_VERIFY` | (list) | Light settings verified to be unchanged. |
| `WP_ACTOR_BATCH_SIZE` | `500` | How many World Partition actors are loaded at once. Lower it if you run out of memory. |
| `RESCAN_INTERVAL` | `2.0` | How often, in seconds, the open map is rescanned while the tool is on. |

After editing the file, restart the editor.

## Troubleshooting

**No menu items under Tools**
- Make sure **Python Editor Script Plugin** is enabled (**Edit → Plugins**) and restart.
- Check the folder layout in step 2. `init_unreal.py` must be at `Plugins/LightMobilityTool/Content/Python/init_unreal.py`.
- Look in the Output Log for Python errors.

**"Not connected to source control"**
- This only appears when `REQUIRE_SOURCE_CONTROL = True`. Connect as described in step 6, or set it back to `False`.

**Maps listed as "file is read-only on disk"**
- **Perforce project:** you aren't connected. Connect (step 6) and run again.
- **Normal project:** the file has its read-only flag set. On Windows, right-click it, choose **Properties**, untick **Read-only**, then run again.

**Maps listed as "not at latest revision"**
- Do **Get Latest** in P4V, restart the editor and run the tool again.

**Maps listed as "checked out by someone else"**
- Ask that person to submit or revert, then run the tool again. It only picks up what's left; lights it already made Movable are left as they are.

**"Files NOT saved" in the report**
- Perforce refused the checkout. The report gives the reason, and the light's change was thrown away rather than force-saved.
  Fix the cause and run again.

**Running it from the Python console**
In the Output Log, switch `Cmd` to `Python`:
```python
import light_mobility_tool as lmt
lmt.preview_all_maps()
lmt.enable()
lmt.disable()
lmt.enable(all_maps=False)   # open level only
```
