# Performance Improvements tab

A dockable editor tab, **Tools → Performance Improvements...**, that:

- **Scans** your project settings and the open level when it opens, or when you click **Scan**.
- Shows every optimization as a row: its **name**, a **description**, its **visual impact**, an **On/Off toggle**,
  and a **suggestion** from the scan, such as "Not enabled: … Turn on to …" or "Active: … Set by this tool."
- **Auto Optimize** measures FPS, turns on the safe settings, measures again, and shows **before → after FPS**.
- **Measure FPS** lets you measure by hand. Measure, toggle settings, then measure again to compare.

## Production safety

**Textures are never touched.**
- Texture settings are on a hard deny list in the code, so the tool *cannot* change them. That covers the streaming pool, mip bias, anisotropy, virtual textures and texture LOD.
- The **Texture quality** check warns you if something in the project is *already* lowering texture quality. It never changes it.
- Screen percentage softens fine texture detail. It's marked **High** visual impact and is never part of Auto Optimize.

**Toggles only change the running editor session.**
- Nothing is written to the project until you click **Save to Project**.
- Restarting the editor discards anything that wasn't saved.
- **Revert All** turns off everything the tool turned on.

**Save to Project** is a separate, explicit step:
- It writes only to `Config/DefaultEngine.ini` → `[SystemSettings]`, and asks first, showing exactly which lines it will add and remove.
- In source control mode it checks the file out first. In local mode it never overwrites a read-only file.
- It backs the file up to `Saved/PerformanceOptimizer/Backups/` and never submits.
- Every line it writes has a marker comment recording the previous value. If your project already had a line for that setting, the marker keeps it word for word.
  When you turn the setting off and save again, the file goes back to exactly how it was, with the same order and line endings.

**Auto Optimize** stays conservative:
- By default it only uses settings with **no** visual change.
- With **Allow low visual impact** ticked, it also uses **Low** settings. These give slightly softer local-light shadows and GI, and turn off motion blur and lens flares.
- It never uses Medium or High settings, never edits levels, and never saves.

**Advice-only rows** cover things that would change the look, such as which lights should cast shadows, light radii, Nanite on assets, and bloom.
They're scanned and explained but never changed automatically. **Select in level** selects the actors involved so you can review them in the Details panel.

**The level toggle** (volumetric fog shadows):
- It only changes the open level, as one undo step (Ctrl+Z).
- It's checked with the same safety check as the light mobility tool: if anything moves or any other setting changes, it's undone.
- It isn't saved for you.

## What's in the list

| Category | Item | Type | What it changes | Visual change | In Auto Optimize |
|---|---|---|---|---|---|
| Frame pacing & pixel streaming | Cap frame rate to the stream rate (60 FPS) | Toggle | `t.MaxFPS = 60` | None | Yes |
| Frame pacing & pixel streaming | VSync off | Toggle | `r.VSync = 0` | None | Yes |
| Resolution | Render at 75% and upscale (TSR / DLSS) | Toggle | `r.ScreenPercentage = 75` | High | No |
| Shadows & lights | Virtual Shadow Map caching | Toggle | `r.Shadow.Virtual.Cache = 1` | None | Yes |
| Shadows & lights | Lighter shadow resolution for local lights | Toggle | `r.Shadow.Virtual.ResolutionLodBiasLocal = 1` | Low | If you allow low impact |
| Shadows & lights | Fewer soft-shadow rays for local lights | Toggle | `r.Shadow.Virtual.SMRT.RayCountLocal = 4` | Low | If you allow low impact |
| Shadows & lights | Use Virtual Shadow Maps instead of ray-traced shadows | Toggle | `r.RayTracing.Shadows = 0` | Medium | No |
| Shadows & lights | MegaLights (UE 5.5+) | Toggle | `r.MegaLights.EnableForProject = 1` | High | No |
| Shadows & lights | Sky Light: no real-time recapture | Toggle | `r.SkyLight.RealTimeReflectionCapture = 0` | Medium | No |
| Shadows & lights | Local lights: no volumetric fog shadows | Toggle | Open level: lights' *Cast Volumetric Shadow* off | Low | No |
| Shadows & lights | Number of shadow-casting lights | Advice | Scan only | Medium | No |
| Shadows & lights | Oversized light radius | Advice | Scan only | Low | No |
| Shadows & lights | Light functions | Advice | Scan only | Medium | No |
| Lumen | Lumen GI: fewer screen probes | Toggle | `r.Lumen.ScreenProbeGather.DownsampleFactor = 32` | Low | If you allow low impact |
| Lumen | Lumen reflections: trace only glossy surfaces | Toggle | `r.Lumen.Reflections.MaxRoughnessToTrace = 0.3` | Low | If you allow low impact |
| Post processing | Motion blur off | Toggle | `r.MotionBlurQuality = 0` | Low | If you allow low impact |
| Post processing | Lens flares off | Toggle | `r.LensFlareQuality = 0` | Low | If you allow low impact |
| Post processing | Convolution bloom | Advice | Scan only | Medium | No |
| Geometry & draw calls | High-poly meshes without Nanite | Advice | Scan only | None | No |
| Geometry & draw calls | Draw calls (number of mesh parts) | Advice | Scan only | None | No |
| Texture quality guard | Texture quality | Advice | Scan only (never changes) | None | No |

Items that don't apply to your project show as **Not applicable**, with the reason. For example, ray-traced shadows when ray tracing is off,
or MegaLights on an engine older than 5.5. Settings already in place show as **Active** with "Already set in your project".

The values (stream FPS, screen percentage, thresholds) are at the top of
`LightMobilityTool/Content/Python/perf_optimizer.py`.

## About the FPS numbers

- **How it measures:** in the **editor viewport**, with the frame cap and editor VSync removed for the measurement and restored afterwards.
  It waits until the frame rate settles, then samples for 5 seconds.
- **Before you start:** keep the editor focused and don't move the camera. The viewport must be in **Realtime** mode (Ctrl+R).
- **Pacing settings aren't in the number.** The frame cap and VSync improve frame pacing and latency in the stream, but they aren't visible in this measurement, so Auto Optimize with "no visual impact" alone often shows about **±0%**.
  The measurable gains come from the Low-impact items and from the manual and advice items.
- **Packaged builds differ.** A packaged pixel-streaming build gets different absolute numbers, but the relative change is a good guide.
  After saving, confirm on the streaming server with `stat unit`.

Every Auto Optimize run writes a report to `Saved/PerformanceOptimizer/Report_<date>.txt`.

## Install

See **[INSTALL.md → Performance Improvements tab](INSTALL.md#10-performance-improvements-tab)**.
