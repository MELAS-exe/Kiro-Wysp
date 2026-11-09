"""Highlight things inside Blender: a 3D object, or a piece of the interface. Never changes scene data.

* Objects: a pulsing bounding box in the 3D viewport.
* Interface elements (``blender://ui/...``, see ``ui_targets``): a pulsing frame around the region plus a
  callout. Properties tabs and the viewport gizmo also get an estimated marker, because Blender's API does
  not expose button rectangles. The frame is exact, the marker is approximate, and the callout says what to find.
"""

from __future__ import annotations

import logging
import math
import time

import bpy
from wysp_adapter_sdk import ErrorCode, WyspError

from . import refs, ui_targets

log = logging.getLogger("wysp.blender")

COLOR = (0.17, 0.83, 0.75)  # the Wysp wisp glow
_state: dict = {
    "object": None,
    "ui": [],
    "until": 0.0,
    "handlers": [],
    "timer": False,
    "broken": False,
    "tabs": [],
    "drawn": set(),
}
_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
_SPACES = {
    "VIEW_3D": "SpaceView3D",
    "OUTLINER": "SpaceOutliner",
    "PROPERTIES": "SpaceProperties",
    "TIMELINE": "SpaceDopeSheetEditor",
}
_ALL_REGIONS = ("WINDOW", "HEADER", "TOOLS", "UI", "NAVIGATION_BAR", "FOOTER", "TOOL_HEADER")


def _windows():
    wm = bpy.context.window_manager
    return getattr(wm, "windows", [])


def _areas():
    for window in _windows():
        yield from window.screen.areas


def _pulse() -> float:
    return 0.55 + 0.45 * math.sin(time.monotonic() * 8.0)


def _ui_scale() -> float:
    prefs = bpy.context.preferences
    return float(prefs.view.ui_scale) * float(prefs.system.pixel_size)


# --------------------------------------------------------------------------- 3D object outline
def _draw_object() -> None:
    name = _state["object"]
    obj = bpy.data.objects.get(name) if name else None
    if obj is None or time.monotonic() > _state["until"]:
        return
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
        from mathutils import Vector

        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        coords = [tuple(corners[i]) for a, b in _EDGES for i in (a, b)]
        shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINES", {"pos": coords})
        shader.uniform_float("color", (*COLOR, max(0.2, _pulse())))
        shader.uniform_float("lineWidth", 4.0)
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        batch.draw(shader)
        gpu.state.blend_set("NONE")
    except Exception:  # noqa: BLE001 - a drawing problem must never break Blender
        _break("object highlight")


def _break(what: str) -> None:
    if not _state["broken"]:
        log.exception("%s drawing failed; disabling it", what)
    _state["broken"] = True


# ------------------------------------------------------------------------- interface highlight
def _rect_lines(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    return [(x, y), (x + w, y), (x + w, y), (x + w, y + h), (x + w, y + h), (x, y + h), (x, y + h), (x, y)]


def _draw_lines(coords, width: float, alpha: float) -> None:
    import gpu
    from gpu_extras.batch import batch_for_shader

    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    batch = batch_for_shader(shader, "LINES", {"pos": coords})
    shader.uniform_float("color", (*COLOR, alpha))
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    batch.draw(shader)


def _fill_rect(x: float, y: float, w: float, h: float, color) -> None:
    import gpu
    from gpu_extras.batch import batch_for_shader

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_callout(region, text: str, x: float | None = None, top: float | None = None) -> None:
    """A dark label with a glowing border. `x` is the left edge (default: centred), `top` the top edge."""
    import blf

    s = _ui_scale()
    blf.size(0, 15 * s)
    tw, th = blf.dimensions(0, text)
    pad = 7 * s
    w, h = min(tw + 2 * pad, max(region.width - 8, 40)), th + 2 * pad
    x = (region.width - w) / 2 if x is None else x
    x = min(max(4, x), max(4, region.width - w - 4))
    top = region.height - 8 * s if top is None else top
    y = min(max(4, top - h), max(4, region.height - h - 4))
    _fill_rect(x, y, w, h, (0.06, 0.09, 0.16, 0.92))
    _draw_lines(_rect_lines(x, y, w, h), 2.0, 0.95)
    blf.color(0, 0.89, 0.91, 0.94, 1.0)
    blf.position(0, x + pad, y + pad + th * 0.12, 0)
    blf.draw(0, text)


def probe_visible_tabs(space) -> list[str]:
    """Tabs the Properties editor shows right now, in display order.

    The RNA enum lists every tab Blender knows; only assigning tells which ones the editor offers for the
    active object. Called once per highlight on the main thread; the caller sets the final tab afterwards.
    """
    current = space.context
    shown = []
    for tab in ui_targets.PROPERTIES_TABS:
        try:
            space.context = tab
            shown.append(tab)
        except (TypeError, ValueError):
            continue
    try:
        space.context = current
    except (TypeError, ValueError):
        pass
    return shown


def tab_marker_rect(
    region_height: float, tabs: list[str], tab: str, s: float
) -> tuple[float, float, float, float] | None:
    """Estimated rectangle of a Properties tab in the navigation bar (approximate: measured on Blender 5.2).

    Tabs are 40 px squares (times the UI scale) from the top of the bar, with a 12 px gap before the
    RENDER group and before the first object-level tab.
    """
    if tab not in tabs:
        return None
    pitch = 40 * s
    y = region_height - 10 * s
    first_object = next((t for t in tabs if t in ui_targets.OBJECT_LEVEL_TABS), None)
    for t in tabs:
        if t in ("RENDER", first_object) and t != tabs[0]:
            y -= 12 * s
        y -= pitch
        if t == tab:
            return (2 * s, y + 1, pitch - 4 * s, pitch - 2)
    return None


def _probe_tabs() -> list[str]:
    for area in _areas():
        if area.type == "PROPERTIES":
            return probe_visible_tabs(area.spaces.active)
    return []


def _overlap_top(area, region) -> float:
    """Height covered by the header bars drawn over the top of a WINDOW region (region overlap)."""
    covered = 0.0
    for r in area.regions:
        if r.type in ("HEADER", "TOOL_HEADER") and r.y >= region.y + region.height - r.height - 2:
            covered += r.height
    return covered


def _draw_ui() -> None:
    if time.monotonic() > _state["until"] or not _state["ui"]:
        return
    try:
        import gpu

        ctx = bpy.context
        area, region = ctx.area, ctx.region
        if area is None or region is None:
            return
        _state["drawn"].add((area.type, region.type))
        s = _ui_scale()
        gpu.state.blend_set("ALPHA")
        alpha = max(0.3, _pulse())
        for target in _state["ui"]:
            if area.ui_type != target.area and area.type != target.area:
                continue
            outlined = (not target.regions and region.type in _ALL_REGIONS) or (
                region.type in target.regions and not target.gizmo
            )
            if outlined:
                inset = 3.0
                _draw_lines(_rect_lines(inset, inset, region.width - 2 * inset, region.height - 2 * inset), 4.0, alpha)
            if target.tab and region.type == "NAVIGATION_BAR":
                rect = tab_marker_rect(region.height, _state["tabs"], target.tab, s)
                if rect:
                    _fill_rect(*rect, (*COLOR, 0.25 * alpha))
                    _draw_lines(_rect_lines(*rect), 3.0, 1.0)
            if target.gizmo and region.type == "WINDOW":
                w, h = 112 * s, 150 * s
                x, top = region.width - w - 8 * s, region.height - _overlap_top(area, region) - 6 * s
                _draw_lines(_rect_lines(x, top - h, w, h), 4.0, alpha)
                _draw_callout(region, target.label, x=region.width, top=top - h - 8 * s)
                continue
            if region.type != target.label_region and not (not target.regions and region.type == "WINDOW"):
                continue
            if region.type == "WINDOW":
                _draw_callout(region, target.label, top=region.height - _overlap_top(area, region) - 8 * s)
            else:
                _draw_callout(region, target.label)
        gpu.state.blend_set("NONE")
    except Exception:  # noqa: BLE001
        _break("interface highlight")


def _register_ui_handlers(targets) -> None:
    for target in targets:
        cls = getattr(bpy.types, _SPACES.get(target.area, ""), None)
        if cls is None:
            log.warning("no space type to draw on for %s", target.area)
            continue
        for region_type in _ALL_REGIONS:
            key = (cls.__name__, region_type)
            if key in _state["handlers"]:
                continue
            try:
                handle = cls.draw_handler_add(_draw_ui, (), region_type, "POST_PIXEL")
            except (ValueError, TypeError, RuntimeError):
                continue
            _state["handlers"].append(key)
            _state.setdefault("handles", {})[key] = handle


# ------------------------------------------------------------------------------ lifecycle
def _tick() -> float | None:
    for area in _areas():
        area.tag_redraw()
    if time.monotonic() > _state["until"]:
        clear_highlight()
        return None
    return 0.04


def clear_highlight() -> None:
    handle = _state.get("object_handle")
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
    for (cls_name, region_type), h in list(_state.get("handles", {}).items()):
        try:
            getattr(bpy.types, cls_name).draw_handler_remove(h, region_type)
        except (ValueError, RuntimeError, AttributeError):
            pass
    _state.update(object=None, object_handle=None, ui=[], handlers=[], handles={}, timer=False, drawn=set())
    try:
        for area in _areas():
            area.tag_redraw()
    except Exception:  # noqa: BLE001
        pass


def _start(duration_ms: int) -> None:
    _state["until"] = time.monotonic() + duration_ms / 1000.0
    if not _state["timer"]:
        _state["timer"] = True
        bpy.app.timers.register(_tick, first_interval=0.02)


def highlight(ref: str, style: str, duration_ms: int) -> dict:
    if bpy.app.background:
        raise WyspError(
            ErrorCode.NOT_SUPPORTED, "there is no window to highlight in when Blender runs in the background"
        )
    if _state["broken"]:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "highlight drawing is disabled after an earlier error")
    if ui_targets.is_ui_ref(ref):
        return _highlight_ui(ref, duration_ms)
    return _highlight_object(ref, duration_ms)


def _highlight_ui(ref: str, duration_ms: int) -> dict:
    target = ui_targets.parse(ref)
    if target is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"unknown interface element {ref}")
    if not any(a.ui_type == target.area or a.type == target.area for a in _areas()):
        raise WyspError(
            ErrorCode.TARGET_NOT_FOUND, f"{target.label} is not visible in the current layout; ask the user to open it"
        )
    if target.tab:
        _state["tabs"] = _probe_tabs()
        from .actions.show_properties_tab import switch_tab

        if not switch_tab(target.tab):
            raise WyspError(
                ErrorCode.PRECONDITION_FAILED, f"the {target.tab} tab is not available for the active object"
            )
    _state["object"] = None
    _state["ui"] = [target]
    _register_ui_handlers([target])
    _start(duration_ms)
    return {"ok": True, "note": target.label}


def _highlight_object(ref: str, duration_ms: int) -> dict:
    mod = refs.parse_modifier_ref(ref)
    obj_name = mod[0] if mod else refs.parse_object_ref(ref)
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    if obj is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"cannot highlight {ref}")
    _state["object"] = obj.name
    _state["ui"] = []
    if mod:
        _state["tabs"] = _probe_tabs()
        from .actions.show_properties_tab import switch_tab

        switch_tab("MODIFIER")
        tab = ui_targets.parse(ui_targets.PREFIX + "properties/tab/MODIFIER")
        if tab is not None:
            _state["ui"] = [tab]
            _register_ui_handlers([tab])
    if _state.get("object_handle") is None:
        _state["object_handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw_object, (), "WINDOW", "POST_VIEW")
    _start(duration_ms)
    return {"ok": True}


# Backwards-compatible name used by earlier code and tests.
highlight_object = highlight
