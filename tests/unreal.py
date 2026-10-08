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
    @staticmethod
    def project_config_dir(): return CONFIG
CONFIG = tempfile.mkdtemp()
class ComponentMobility(enum.Enum):
    STATIC = 0; STATIONARY = 1; MOVABLE = 2
class Name(str): pass
class Pkg:
    def __init__(s, n): s.n = n
    def get_name(s): return s.n
DIRTY = set()
_ids = [0]
class Vec:
    def __init__(s, x=0.0, y=0.0, z=0.0): s.x, s.y, s.z = x, y, z
class Rot:
    def __init__(s, r=0.0, p=0.0, y=0.0): s.roll, s.pitch, s.yaw = r, p, y
class Obj:
    def __init__(s, pkg):
        s._pkg = pkg; _ids[0] += 1; s._id = _ids[0]
    def get_package(s): return Pkg(s._pkg)
    def get_outermost(s): return Pkg(s._pkg)
    def get_path_name(s): return "{}:obj{}".format(s._pkg, s._id)
class SceneComponent(Obj):
    def __init__(s, owner, mob, name, parent=None, editor_only=False):
        super().__init__(owner._pkg); s.owner = owner; s.name = name; s.parent = parent; s.children = []
        s.props = {"mobility": mob, "component_tags": [], "is_editor_only": editor_only,
                   "intensity": 5.0, "light_color": (1, 1, 1), "cast_shadows": True,
                   "cast_volumetric_shadow": True, "volumetric_scattering_intensity": 1.0,
                   "attenuation_radius": 1000.0, "light_function_material": None}
        if parent: parent.children.append(s)
    def get_owner(s): return s.owner
    def get_name(s): return s.name
    def get_editor_property(s, k): return s.props[k]
    def set_editor_property(s, k, v):
        if s.props.get(k) != v: DIRTY.add(s._pkg)
        s.props[k] = v
        if k == "mobility" and SIDE_EFFECT[0]: SIDE_EFFECT[0](s)
    def get_world_location(s): return Vec(*s.owner.loc)
    def get_world_rotation(s): return Rot(s.owner.roll, s.owner.pitch, s.owner.yaw)
    def get_world_scale(s): return Vec(1, 1, 1)
    def get_world_transform(s): return (tuple(s.owner.loc), s.owner.yaw)
    def set_world_transform(s, t, sweep, teleport): s.owner.loc, s.owner.yaw = list(t[0]), t[1]
    def get_attach_parent(s): return s.parent
    def get_children_components(s, all_desc):
        out = []
        for c in s.children:
            out.append(c); out += c.get_children_components(True)
        return out
SIDE_EFFECT = [None]
class LightComponentBase(SceneComponent): pass
class LocalLightComponent(LightComponentBase): pass
class SkyLightComponent(LightComponentBase):
    def __init__(s, owner, mob):
        super().__init__(owner, mob, "SkyLightComponent0"); s.props["real_time_capture"] = True
class ExponentialHeightFogComponent(SceneComponent):
    def __init__(s, owner, volumetric):
        super().__init__(owner, MOVABLE_DEFAULT[0], "Fog"); s.props["enable_volumetric_fog"] = volumetric
MOVABLE_DEFAULT = [None]
class StaticMeshComponent(SceneComponent): pass
class ArrowComponent(SceneComponent): pass
class DirectionalLightComponent(LightComponentBase):
    def __init__(s, owner, mob): super().__init__(owner, mob, "LightComponent0")
class InstancedStaticMeshComponent(StaticMeshComponent): pass
class PostProcessVolume: pass
class Comp(LocalLightComponent):
    def __init__(s, owner, mob): super().__init__(owner, mob, "LightComponent0")
class Actor(Obj):
    def __init__(s, label, pkg, mobs):
        super().__init__(pkg); s.label = label; s.loc = [0.0, 0.0, 0.0]; s.yaw = 0.0
        s.pitch = 0.0; s.roll = 0.0
        s.comps = [Comp(s, m) for m in mobs]; s.others = []
    def get_actor_label(s): return s.label
    def get_components_by_class(s, c):
        return [x for x in list(s.comps) + list(s.others) if isinstance(x, c)]
    def get_actor_location(s): return Vec(*s.loc)
    def get_actor_rotation(s): return Rot(s.roll, s.pitch, s.yaw)
    def get_actor_scale3d(s): return Vec(1, 1, 1)
    def get_actor_transform(s): return (tuple(s.loc), s.yaw)
    def set_actor_transform(s, t, sweep, teleport): s.loc, s.yaw = list(t[0]), t[1]
    def get_attached_actors(s): return []
    def get_attach_parent_actor(s): return None
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
    def set_selected_level_actors(s, actors): STATE.selected = list(actors)
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
TICKS = []
def register_slate_post_tick_callback(f): TICKS.append(f); return len(TICKS)
CVARS = {}
class SystemLibrary:
    @staticmethod
    def get_engine_version(): return ENGINE_VERSION[0]
    @staticmethod
    def get_console_variable_float_value(n): return float(CVARS.get(n, 0.0))
    @staticmethod
    def execute_console_command(world, cmd):
        name, value = cmd.split(" ", 1)
        if name in READ_ONLY: return
        CVARS[name] = float(value)
ENGINE_VERSION = ["5.4.4-0+++UE5+Release-5.4"]
READ_ONLY = set()
def unregister_slate_post_tick_callback(h): pass
def uclass(): return lambda c: c
def ufunction(**kw): return lambda f: f
class ToolMenuEntryScript: pass
class CheckBoxState(enum.Enum):
    CHECKED = 0; UNCHECKED = 1
class ToolMenus:
    @staticmethod
    def get():
        class _M:
            def find_menu(s, name): return None
        return _M()
