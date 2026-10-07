# Unreal runs every init_unreal.py found in a plugin's Content/Python folder
# when the editor starts. This just registers the menu toggle.
import light_mobility_tool

light_mobility_tool.startup()
