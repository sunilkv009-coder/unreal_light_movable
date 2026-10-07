"""
Light Mobility Tool
===================

Editor toggle that forces every light in the open level to Movable.

* ON  -> every light component (Point, Spot, Rect, Directional, Sky light,
         plus light components inside Blueprint actors) is set to Movable.
         Its original mobility is saved as a component tag so it can be put
         back later. Lights added while the toggle is on are made Movable too.
* OFF -> every light the tool changed is set back to its original mobility
         (Static / Stationary) and the tag is removed.

The on/off state survives editor restarts (stored in Saved/LightMobilityTool.json).

Usage from the editor:  Tools menu -> "Force Lights Movable"
Usage from Python / the Output Log (Cmd: Python):
    import light_mobility_tool as lmt
    lmt.enable()   # or lmt.disable(), lmt.toggle(), lmt.is_enabled()
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
# Watcher: keeps new / changed lights Movable while enabled
# --------------------------------------------------------------------------

def _on_tick(delta_seconds):
    global _time_since_scan

    _time_since_scan += delta_seconds
    if _time_since_scan < RESCAN_INTERVAL:
        return
    _time_since_scan = 0.0

    if _editor_world() is None:
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


def enable():
    global _enabled
    _enabled = True
    _save_state()
    make_all_lights_movable()
    _start_watcher()
    _log("ON - all lights are forced to Movable.")


def disable():
    global _enabled
    _enabled = False
    _save_state()
    _stop_watcher()
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
        "When checked, every light in the level is set to Movable (no Static/Stationary). "
        "Uncheck to restore each light's original mobility.",
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
