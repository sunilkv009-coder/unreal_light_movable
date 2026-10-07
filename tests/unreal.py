# Fake of the parts of the Unreal Python API the tool uses (tests only).
import enum, tempfile, types
SAVED = tempfile.mkdtemp()
logs = []
def log(m): logs.append(("log", m))
def log_warning(m): logs.append(("warn", m))
def log_error(m): logs.append(("err", m))
import os
CONTENT = tempfile.mkdtemp()
class Paths:
    @staticmethod
    def project_saved_dir(): return SAVED
    @staticmethod
    def project_content_dir(): return CONTENT
    @staticmethod
    def project_plugins_dir(): return os.path.join(CONTENT, "..", "NoPlugins")
    @staticmethod
    def convert_relative_path_to_full(p): return os.path.abspath(p)
class ComponentMobility(enum.Enum):
    STATIC = 0; STATIONARY = 1; MOVABLE = 2
class Name(str): pass
class Pkg:
    def __init__(s, n): s.n = n
    def get_name(s): return s.n
DIRTY = set()
class Obj:
    def __init__(s, pkg): s._pkg = pkg
    def get_package(s): return Pkg(s._pkg)
    def get_outermost(s): return Pkg(s._pkg)
class LightComponentBase: pass
class Comp(Obj):
    def __init__(s, owner, mob):
        super().__init__(owner._pkg); s.owner = owner; s.props = {"mobility": mob, "component_tags": []}
    def get_owner(s): return s.owner
    def get_name(s): return "LightComponent0"
    def get_editor_property(s, k): return s.props[k]
    def set_editor_property(s, k, v):
        if s.props[k] != v: DIRTY.add(s._pkg)
        s.props[k] = v
class Actor(Obj):
    def __init__(s, label, pkg, mobs):
        super().__init__(pkg); s.label = label; s.comps = [Comp(s, m) for m in mobs]
    def get_actor_label(s): return s.label
    def get_components_by_class(s, c): return s.comps
class World(Obj): pass
STATE = types.SimpleNamespace(world=None, maps={}, loaded=[], sc=True, files={}, saved=[], pie=False, wp={})
class UnrealEditorSubsystem:
    def get_editor_world(s): return STATE.world
class LevelEditorSubsystem:
    def is_in_play_in_editor(s): return STATE.pie
    def load_level(s, p):
        if p not in STATE.maps: return False
        DIRTY.clear()
        STATE.world = World(p); STATE.loaded = list(STATE.maps[p]["actors"]); STATE.wp_loaded = []
        return True
class EditorActorSubsystem:
    def get_all_level_actors(s): return list(STATE.loaded) + list(getattr(STATE, "wp_loaded", []))
def get_editor_subsystem(c): return c()
class ScopedEditorTransaction:
    def __init__(s, n): pass
    def __enter__(s): return s
    def __exit__(s, *a): pass
class ScopedSlowTask(ScopedEditorTransaction):
    def __init__(s, n, t): pass
    def make_dialog(s, b): pass
    def should_cancel(s): return False
    def enter_progress_frame(s, n, t): pass
class FState:
    def __init__(s, **kw):
        d = dict(is_valid=True, is_checked_out=False, is_added=False, is_source_controlled=True,
                 is_checked_out_other=False, checked_out_other="", is_current=True, is_deleted=False, can_check_out=True)
        d.update(kw); s.d = d
    def get_editor_property(s, k): return s.d[k]
class SourceControl:
    @staticmethod
    def is_enabled(): return STATE.sc
    @staticmethod
    def query_file_state(f, silent): return STATE.files.get(f, FState())
    @staticmethod
    def check_out_file(f, silent):
        st = STATE.files.setdefault(f, FState()); st.d["is_checked_out"] = True; STATE.checkouts.append(f); return True
    @staticmethod
    def last_error_msg(): return ""
class EditorLoadingAndSavingUtils:
    @staticmethod
    def get_dirty_map_packages(): return [Pkg(n) for n in sorted(DIRTY)]
    @staticmethod
    def get_dirty_content_packages(): return []
    @staticmethod
    def save_packages(pkgs, only_dirty):
        for p in pkgs:
            if STATE.sc:
                assert STATE.files.get(p.get_name(), FState()).d["is_checked_out"], "saved without checkout: " + p.get_name()
            else:
                f = Paths.project_content_dir() + p.get_name()[len("/Game"):] + ".umap"
                assert not os.path.exists(f) or os.access(f, os.W_OK), "overwrote read-only file " + f
            STATE.saved.append(p.get_name()); DIRTY.discard(p.get_name())
        return True
    @staticmethod
    def save_dirty_packages_with_dialog(a, b): return True
class TopLevelAssetPath:
    def __init__(s, a, b): pass
class ARFilter:
    def __init__(s, **kw): pass
class AssetRegistryHelpers:
    @staticmethod
    def get_asset_registry():
        class R:
            def wait_for_completion(s): pass
            def get_assets(s, f): return [types.SimpleNamespace(package_name=m) for m in STATE.maps]
        return R()
class WorldPartitionBlueprintLibrary:
    @staticmethod
    def get_actor_descs():
        return (True, [types.SimpleNamespace(get_editor_property=lambda k, g=g: g) for g in STATE.maps[STATE.world._pkg].get("wp", {})])
    @staticmethod
    def load_actors(gs):
        STATE.wp_loaded = STATE.wp_loaded + [STATE.maps[STATE.world._pkg]["wp"][g] for g in gs]
    @staticmethod
    def unload_actors(gs):
        wp = STATE.maps[STATE.world._pkg]["wp"]
        STATE.wp_loaded = [a for a in STATE.wp_loaded if a not in [wp[g] for g in gs]]
class AppMsgType(enum.Enum):
    OK = 0; YES_NO = 1
class AppReturnType(enum.Enum):
    YES = 0; NO = 1
DIALOGS = []
class EditorDialog:
    @staticmethod
    def show_message(t, m, k): DIALOGS.append(m); return AppReturnType.YES
def register_slate_post_tick_callback(f): return 1
def unregister_slate_post_tick_callback(h): pass
def uclass(): return lambda c: c
def ufunction(**kw): return lambda f: f
class ToolMenuEntryScript: pass
class CheckBoxState(enum.Enum):
    CHECKED = 0; UNCHECKED = 1
