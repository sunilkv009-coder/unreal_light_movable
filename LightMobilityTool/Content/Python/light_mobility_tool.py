"""
Light Mobility Tool
===================

Editor toggle that forces every light in every map of the project to Movable.

* ON  -> every map under MAP_ROOTS (default: /Game) is opened one by one and
         every light component (Point, Spot, Rect, Directional, Sky light,
         plus light components inside Blueprint actors) is set to Movable,
         then the map is saved. Its original mobility is saved as a component
         tag so it can be put back later. While ON, lights added to whatever
         map is open are made Movable too.
* OFF -> every map is opened again, every light the tool changed is set back
         to its original mobility (Static / Stationary), the tag is removed and
         the map is saved.

World Partition maps are handled by loading their actors in batches.

The on/off state survives editor restarts (stored in Saved/LightMobilityTool.json).

Usage from the editor:  Tools menu -> "Force Lights Movable"
Usage from Python / the Output Log (Cmd: Python):
    import light_mobility_tool as lmt
    lmt.enable()   # or lmt.disable(), lmt.toggle(), lmt.is_enabled()
    lmt.process_all_maps(make_movable=True)   # one-shot, no toggle
    lmt.make_all_lights_movable()             # current level only
"""

import json
import os

import unreal

# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

# Prefix of the component tag that stores the original mobility.
TAG_PREFIX = "LightMobilityTool.Original="

# While enabled, the level is re-scanned this often (seconds) so new or
# manually-changed lights get switched to Movable as well.
RESCAN_INTERVAL = 2.0

# Content folders searched for maps. Add e.g. "/MyPlugin" to include plugin maps.
MAP_ROOTS = ["/Game"]

# World Partition maps: how many actors to load into memory at once.
WP_ACTOR_BATCH_SIZE = 500

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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _log(msg):
    unreal.log("[LightMobilityTool] " + msg)


def _mobility_name(mobility):
    for name, value in _MOBILITY_BY_NAME.items():
        if value == mobility:
            return name
    return None


def _editor_world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _level_actors():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()


def _light_components(actors=None):
    """Every light component in the level, including ones inside Blueprint actors."""
    for actor in actors if actors is not None else _level_actors():
        for comp in actor.get_components_by_class(unreal.LightComponentBase):
            yield comp


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
# Core operations
# --------------------------------------------------------------------------

def make_all_lights_movable(actors=None):
    """Set every non-movable light to Movable, remembering its original mobility."""
    todo = [c for c in _light_components(actors)
            if c.get_editor_property("mobility") != unreal.ComponentMobility.MOVABLE]
    if not todo:
        return 0
    # One undo step for the whole batch (Ctrl+Z reverts it).
    with unreal.ScopedEditorTransaction("Force Lights Movable"):
        for comp in todo:
            current = comp.get_editor_property("mobility")
            # Only record the first original value, so a light that was Static,
            # then manually set to Stationary while the tool was on, still
            # restores to Static.
            if _get_saved_mobility(comp) is None:
                _set_saved_mobility(comp, current)
            # set_editor_property runs PostEditChange, so the editor updates
            # lighting/shadows exactly as if you changed it in the Details panel.
            comp.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    _log("Set {} light(s) to Movable.".format(len(todo)))
    return len(todo)


def restore_original_mobility(actors=None):
    """Put back the mobility of every light this tool changed."""
    todo = [(c, _get_saved_mobility(c)) for c in _light_components(actors)]
    todo = [(c, m) for c, m in todo if m is not None]
    if not todo:
        return 0
    with unreal.ScopedEditorTransaction("Restore Light Mobility"):
        for comp, original in todo:
            comp.set_editor_property("mobility", original)
            _set_saved_mobility(comp, None)
    _log("Restored original mobility on {} light(s).".format(len(todo)))
    return len(todo)


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
    return sorted({str(a.package_name) for a in registry.get_assets(ar_filter)})


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


def _save_dirty_maps():
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, False)


def _process_open_map(make_movable):
    """Apply/restore on the open map (all of it, even unloaded WP cells) and save."""
    func = make_all_lights_movable if make_movable else restore_original_mobility
    count = func()
    _save_dirty_maps()

    guids = _world_partition_actor_guids()
    if guids:
        lib = unreal.WorldPartitionBlueprintLibrary
        for i in range(0, len(guids), WP_ACTOR_BATCH_SIZE):
            batch = guids[i:i + WP_ACTOR_BATCH_SIZE]
            lib.load_actors(batch)
            count += func()
            _save_dirty_maps()
            lib.unload_actors(batch)
    return count


def process_all_maps(make_movable=True, maps=None):
    """
    Open every map, make its lights Movable (or restore them), and save it.
    Returns the number of lights changed. Re-opens the map you started on.
    """
    global _batch_running

    level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if level_editor.is_in_play_in_editor():
        unreal.log_warning("[LightMobilityTool] Stop Play-In-Editor first.")
        return 0

    # Let the user save (or not) whatever they were working on before we switch maps.
    if not unreal.EditorLoadingAndSavingUtils.save_dirty_packages_with_dialog(True, True):
        _log("Cancelled.")
        return 0

    world = _editor_world()
    start_map = world.get_outermost().get_name() if world else None
    maps = maps if maps is not None else find_all_maps()

    total = 0
    done_maps = 0
    _batch_running = True
    try:
        verb = "Making lights Movable" if make_movable else "Restoring light mobility"
        with unreal.ScopedSlowTask(len(maps), verb + " in all maps...") as task:
            task.make_dialog(True)
            for map_path in maps:
                if task.should_cancel():
                    unreal.log_warning("[LightMobilityTool] Cancelled after {} map(s).".format(done_maps))
                    break
                task.enter_progress_frame(1, "{}: {}".format(verb, map_path))
                if not level_editor.load_level(map_path):
                    unreal.log_warning("[LightMobilityTool] Could not open {}".format(map_path))
                    continue
                count = _process_open_map(make_movable)
                if count:
                    _log("{}: {} light(s)".format(map_path, count))
                total += count
                done_maps += 1
    finally:
        _batch_running = False
        if start_map and start_map.startswith("/") and not start_map.startswith("/Temp/"):
            level_editor.load_level(start_map)

    _log("Done: {} light(s) changed across {} map(s).".format(total, done_maps))
    return total


# --------------------------------------------------------------------------
# Watcher: keeps new / changed lights Movable while enabled
# --------------------------------------------------------------------------

def _on_tick(delta_seconds):
    global _time_since_scan

    _time_since_scan += delta_seconds
    if _time_since_scan < RESCAN_INTERVAL:
        return
    _time_since_scan = 0.0

    if _batch_running or _editor_world() is None:
        return
    # Don't touch anything while Play-In-Editor is running.
    if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
        return
    # Also covers opening a different level: its lights get switched here.
    make_all_lights_movable()


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


def enable(all_maps=True, ask=True):
    """Turn ON: make every light in every map Movable (or just the open level)."""
    global _enabled
    if all_maps:
        maps = find_all_maps()
        if ask and not _confirm(
                "Open and save all {} map(s) under {}, setting every light to Movable?\n\n"
                "Original mobility is remembered, so turning the tool off restores it."
                .format(len(maps), ", ".join(MAP_ROOTS))):
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
    if all_maps:
        maps = find_all_maps()
        if ask and not _confirm(
                "Open and save all {} map(s), restoring every light's original mobility?"
                .format(len(maps))):
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
# Menu entry (Tools -> Force Lights Movable), shown as a checkbox
# --------------------------------------------------------------------------

@unreal.uclass()
class LightMobilityToggleEntry(unreal.ToolMenuEntryScript):

    @unreal.ufunction(override=True)
    def execute(self, context):
        toggle()

    @unreal.ufunction(override=True)
    def get_check_state(self, context):
        return unreal.CheckBoxState.CHECKED if _enabled else unreal.CheckBoxState.UNCHECKED


def _register_menu():
    menus = unreal.ToolMenus.get()
    menu = menus.find_menu(MENU_NAME)
    if menu is None:
        unreal.log_warning("[LightMobilityTool] Could not find menu '{}'.".format(MENU_NAME))
        return

    menu.add_section(MENU_SECTION, "Lighting")

    entry = LightMobilityToggleEntry()
    entry.init_entry(
        MENU_OWNER,
        MENU_NAME,
        MENU_SECTION,
        "ForceLightsMovable",
        "Force Lights Movable",
        "When checked, every light in every map is set to Movable (no Static/Stationary) "
        "and the maps are saved. Uncheck to restore each light's original mobility.",
    )
    advanced = entry.data.advanced
    advanced.user_interface_action_type = unreal.UserInterfaceActionType.TOGGLE_BUTTON
    entry.data.advanced = advanced

    menu.add_menu_entry_object(entry)
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
