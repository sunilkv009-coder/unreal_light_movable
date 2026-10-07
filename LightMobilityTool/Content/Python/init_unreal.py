# Unreal runs every init_unreal.py found in a plugin's Content/Python folder
# when the editor starts. This registers the Tools menu entries.
import light_mobility_tool

light_mobility_tool.startup()

try:
    import perf_optimizer

    perf_optimizer.startup()
except Exception:
    import traceback

    import unreal

    unreal.log_error("[PerformanceOptimizer] Failed to start:\n" + traceback.format_exc())
