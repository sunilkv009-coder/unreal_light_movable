# Camera Match (from Photo): fSpy for Unreal

A dockable editor tab, **Tools → Camera Match (from Photo)...**, that works like [fSpy](https://fspy.io):

1. Load a photo (the backplate).
2. Drag colored lines onto edges in the photo that are parallel in the real world.
3. The tool works out the camera: **focal length, field of view, position and rotation**.
4. **Create Camera** adds a **Cine Camera** to the level with those settings and the photo as a **backplate**,
   so 3D objects you place line up with the photo when you look through it.

Everything happens inside the editor. The tool draws a ground grid and the world axes on the photo
with the solved camera, so you can check the match before you create the camera.

---

## Quick start

1. **Install** the plugin: double-click **`Build-CameraMatch.bat`** and pick your `.uproject` (see [Install](#install)).
2. Open **Tools → Camera Match (from Photo)...**
3. Click **Load Image File...** and pick the photo. Or select a texture in the Content Browser and click **Use Selected Texture**.
4. Leave the method on **2 vanishing points** and drag the handles:
   - the two **VP1** lines onto two edges that run in one direction (for example the bottom and top of the left wall of a building);
   - the two **VP2** lines onto two edges that run at 90° to that (the right wall);
   - the **Origin** handle onto a point on the ground, for example the bottom of the corner.
5. Check the **ground grid**: it should lie flat on the ground in the photo, and the blue Z axis should point straight up.
6. Under **Scale**, pick **Camera height** and enter how high the camera was (about 160 cm for a hand-held photo),
   or use **Known length** with something you know the size of.
7. Click **Create Camera**, then **Pilot Camera**. You're looking through a camera that matches the photo, with the photo shown at 50% over the scene.

## The tab

| Section | What it does |
|---|---|
| **1. Photo** | **Load Image File...** opens a PNG, JPG, BMP, TGA, EXR or TIFF. It's imported into the project (`/Game/CameraMatch/Backplates`) only when you create a camera. **Use Selected Texture** uses a texture that's already in the project. |
| **2. Method** | **2 vanishing points** works out the focal length from two perpendicular sets of lines. **1 vanishing point** uses one set of lines plus the horizon, and you enter the focal length. |
| **3. Axes** | Which Unreal axis each set of lines runs along, **in the direction towards where the lines meet**. X is red, Y green, Z blue (up). |
| **4. Lens** | Sensor size (long side, mm) and, for 1 vanishing point, the focal length. |
| **5. Scale** | How big the scene is: camera **distance** to the origin, camera **height** above the ground, or a **known length** along an axis. |
| **6. Overlay** | Ground grid and axes, the horizon, and the control lines extended across the view. |
| **Solved camera** | Focal length, sensor, field of view, location and rotation, plus any errors or warnings. |
| **7. Unreal camera** | Backplate options, **Create Camera**, **Update Camera**, **Pilot Camera** and **Edit Selected Camera**. |

### The canvas (right side)

- **Drag** a handle to move it. Hold **Shift** to move it slowly, for precise placement. A **magnifier** shows the area under the handle while you drag.
- **Mouse wheel** zooms. **Right or middle drag**, or a left drag on empty space, pans. **F** (or **Fit**) shows the whole photo.
- **Reset Lines** puts every handle back in its starting layout.
- The lines are colored by the axis you picked for them. When the camera is solved, it also draws:
  the **ground grid** (Z = 0), the **X/Y/Z axes** at the origin, the **horizon** (yellow), and the **vanishing points** (VP1, VP2 and the third one, VP3).
- If the lines can't give a camera, a red bar at the top says why, and the full message is under **Solved camera**.

## Choosing lines and axes

**2 vanishing points** (the default) needs edges in two directions at 90° to each other, like the two sides of
a building, a room, a box, a road and the kerb across it, or floor tiles.

- Put the lines **as far apart as you can**: the bottom and top of a wall work better than two lines close together.
- Use long edges, and zoom in to place the ends accurately.
- Make the two directions horizontal (X and Y) when you can. Then the third axis, Z, is up.

**Picking the axes.** For each set of lines, pick the axis the edges run along, signed so it points *towards* where the lines meet.
The defaults (VP1 = **+X** on the left, VP2 = **+Y** on the right) give Z up for a photo of a corner seen from the outside.
If the grid comes out upside down (the tool warns you) or mirrored, change the sign of one axis (for example **+X** to **−X**).
You can also use a vertical direction: for a tall building seen from below, use VP1 = **+Z** on the vertical edges.

**1 vanishing point** is for photos where only one direction converges, like a road or corridor seen head on.
- Put the two **VP1** lines on edges that run away from the camera.
- Turn the **horizon line** to follow the horizon (or any horizontal edge that runs across the photo). Its arrow shows
  which way its axis points; drag its ends to flip it.
- Enter the **focal length** (from the photo's EXIF data) and the **sensor size**.

**Origin.** The world origin (0,0,0) goes where the **Origin** handle is. Put it on the ground, on a point you can identify.
Unreal's ground is Z = 0, so the grid is drawn on the plane through the origin made by X and Y.

## Scale

A photo alone can't tell how big things are, so pick one:

- **Distance:** the camera is this many cm from the origin. Use it when the size doesn't matter.
- **Camera height:** the camera is this many cm above the ground. About 150–170 cm for a hand-held photo, 100–120 cm for car shots.
  The origin must be on the ground, below the horizon.
- **Known length:** pick an axis, then drag the **reference** handle from the origin along that axis to a point at a known distance,
  such as a door width, a car's wheelbase or a floor tile, and enter that distance. The handle stays on the axis line.

## The Unreal camera

**Create Camera** adds a **Cine Camera Actor** to the open level, in the outliner folder `CameraMatch`, with:

- the solved **location and rotation**;
- a **filmback** with the photo's aspect ratio (sensor size from section 4) and the solved **focal length**, so the frame matches the photo exactly;
- **Constrain Aspect Ratio** on, and **depth of field off** (focus method Disable);
- the **backplate**, if **Show the photo through the camera** is ticked.

It's one undo step (Ctrl+Z). The camera is then **linked**: with **Live update** on, dragging lines or changing settings moves it
straight away (one undo step per drag), and **Update Camera** applies everything, including the backplate options.

**Pilot Camera** looks through the camera in the level viewport. To stop, click the eject button at the top left of the viewport.
Press **G** (Game View) to hide the editor icons.

**Edit Selected Camera** reopens a camera made with this tool: select it in the level and click the button. Its lines, settings and
photo come back and it becomes the linked camera. The tool stores them in one of the camera's **Tags** (`CameraMatch:...`), so they're
saved with the level. Don't remove that tag if you want to edit the camera later.

### The backplate

The photo is shown by a **post-process material on the camera itself**, not by an object in the level:

- It's **exactly framed**: it's drawn in screen space, so it always fills the camera's view, at any focal length.
- **Only this camera shows it.** It doesn't cast shadows, light the scene, or appear in reflections.
- **Backplate opacity:** 0.5 (the default) shows the scene and the photo together, which is the easiest way to check the match.
  1 shows only the photo.
- **Photo only behind 3D objects:** the photo replaces empty space and the sky, and your 3D objects sit in front of it.
- It's drawn after the tonemapper, with the photo's original colors, so exposure and color grading don't change the photo.

Assets the tool creates, all in `/Game/CameraMatch`:

| Asset | What it is |
|---|---|
| `Backplates/T_<photo>` | The photo, imported when you first create a camera from a file. |
| `M_CameraMatchBackplate` | The backplate material (shared). Parameters: `Backplate`, `Opacity`, `BehindScene`, `SkyDepth`. |
| `MI_<camera>` | One material instance per camera, with its photo and options. |

They are **not saved for you**: use **File → Save All**. With Perforce, Unreal marks the new files for add when you save them.
Nothing is ever submitted.

**Rendering with the backplate.** The backplate also shows up in Movie Render Queue renders from that camera. For a clean
render, set the opacity to 0 (and click **Update Camera**), or untick **Show the photo through the camera** and click **Update Camera**.

## Tips for an accurate match

- **Lens distortion:** the tool assumes straight lines stay straight. Wide-angle and phone photos often bend lines near the edges.
  Undistort the photo first (Lightroom, Photoshop *Lens Correction*, Nuke, or RawTherapee), or use edges near the middle of the photo.
- **Cropped photos:** the tool assumes the lens centre is the centre of the image. A photo cropped off-centre will match slightly worse.
  Use the uncropped original if you can.
- **Sensor size** only changes the focal length number (and the filmback). The match on screen is the same for any sensor size.
  Use the real camera's sensor if you want the focal length to match the lens.
- Compare the grid with several things in the photo, not just the lines you used. If the grid drifts away from the ground at the edges,
  try lines that are further apart, or check for lens distortion.

## How it works

The method is the one fSpy uses, from *Guillou et al., "Using vanishing points for camera calibration and coarse 3D reconstruction from a single image"* (2000):

1. Each pair of lines is intersected to find its **vanishing point**.
2. With **2 vanishing points** `V1`, `V2` (relative to the image centre), the rays to them must be perpendicular, so the focal length is
   `f = sqrt(-(V1 · V2))`. With **1 vanishing point**, `f` comes from your focal length, and the second direction is the one in the
   plane of the horizon line that's perpendicular to the first.
3. The two directions, signed by the axes you picked, give two columns of the camera rotation. The third column is their cross product,
   with the sign that makes it a valid **left-handed** Unreal frame (X forward, Y right, Z up).
4. The origin handle gives the direction from the camera to the world origin. The scale option gives the distance along it, which
   places the camera.
5. The rotation is converted to an `FRotator` the same way Unreal's own `FMatrix::Rotator()` does.

The solver (`CameraMatch/Source/CameraMatch/Private/CameraMatchSolver.cpp`) has no Unreal dependencies. Its tests build photos from
known Unreal cameras, using Unreal's rotation and projection conventions, and check that the solver gets each camera back
(focal length, rotation, location and reprojection), including portrait photos, vertical vanishing points, all three scale options,
the error cases and the default handle layout. Run them with `python3 tests/test_camera_match.py` (needs g++ or clang++).

## Limits

- The principal point is always the image centre (no lens shift). fSpy's "principal point from a 3rd vanishing point" isn't supported.
- No lens distortion correction (see the tips above).
- The grid is drawn on the ground plane (X/Y) only.
- The backplate assumes a normal SDR project: it's drawn after the tonemapper, where colors are sRGB encoded. With HDR output the photo's colors will be off.
- The photo must be an sRGB texture (any normal JPG/PNG) without Virtual Texture Streaming. The tool turns Virtual Texture Streaming off
  on photos it imports itself, and tells you if a texture you picked can't be used.
- It doesn't read or write `.fspy` project files.

## Install

The plugin is C++ (`CameraMatch/`), so it has to be compiled once, like the Performance Improvements tab.
It doesn't need the Light Mobility Tool or Python.

**One double-click (recommended)**

1. Install **Visual Studio 2022** with **Game development with C++** and **Desktop development with C++** (see [INSTALL.md](INSTALL.md#10-easy-one-double-click-recommended)).
2. Close Unreal.
3. Double-click **`Build-CameraMatch.bat`** (or drag your `.uproject` onto it) and pick your project.
   It compiles the plugin with Unreal's own build tool and copies it to `YourProject/Plugins/CameraMatch/`.
4. Open the project and go to **Tools → Camera Match (from Photo)...**

**By hand**

- **C++ project:** copy `CameraMatch` to `YourProject/Plugins/CameraMatch/`, regenerate the project files and build the editor.
- **Blueprint-only project:** build it once with
  `RunUAT.bat BuildPlugin -Plugin="C:\path\to\CameraMatch\CameraMatch.uplugin" -Package="C:\Temp\CameraMatch_Built" -TargetPlatforms=Win64`
  and copy `C:\Temp\CameraMatch_Built` to `YourProject/Plugins/CameraMatch/`.
- **Perforce:** submit `Plugins/CameraMatch/` (with `Binaries/` if artists don't compile, without `Intermediate/`).

**Engine versions:** written for Unreal Engine 5.1 and later (5.3+ recommended). If the build fails, the script prints the error lines
and the log path. Send those, with your engine version, to get the code fixed.

## Troubleshooting

- **"These two vanishing points can't come from a real camera":** the two sets of lines don't belong to perpendicular directions,
  or a line is on the wrong edge. Each pair must follow edges that are parallel in the real world, and the two directions must be at 90°.
- **"The two lines of vanishing point 1 are parallel":** those edges are parallel to the photo, so they never meet. Use edges that
  converge, or switch to **1 vanishing point**.
- **The grid is upside down or mirrored:** change the sign of one axis (for example VP1 **+X** to **−X**).
- **The grid is right but the camera is too big or small:** that's the scale. Use **Camera height** or **Known length**.
- **I can't see the photo when I pilot the camera:** check **Show the photo through the camera** is ticked and the opacity isn't 0, then **Update Camera**.
  Use the *Lit* view mode: post-process materials don't show in Wireframe and some other view modes.
- **The photo looks blurry in the tab:** for textures from the Content Browser, the editor may still be streaming the full resolution in.
  Give it a moment, or use **Load Image File...** with the original file.
