"""Highlight an object in the 3D viewport: a pulsing outline of its bounding box. Never changes scene data."""

from __future__ import annotations

import logging
import math
import time

import bpy
from wysp_adapter_sdk import ErrorCode, WyspError

from . import refs

log = logging.getLogger("wysp.blender")

COLOR = (0.17, 0.83, 0.75)  # the Wysp wisp glow
_state: dict = {"handle": None, "object": None, "until": 0.0, "timer": False, "broken": False}
_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))


def _viewports():
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", []):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                yield area


def _draw() -> None:
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
        alpha = 0.55 + 0.45 * math.sin(time.monotonic() * 8.0)
        shader.uniform_float("color", (*COLOR, max(0.2, alpha)))
        shader.uniform_float("lineWidth", 4.0)
        shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("NONE")
        batch.draw(shader)
        gpu.state.blend_set("NONE")
    except Exception:  # noqa: BLE001 - a drawing problem must never break Blender
        if not _state["broken"]:
            log.exception("highlight drawing failed; disabling it")
        _state["broken"] = True


def _tick() -> float | None:
    for area in _viewports():
        area.tag_redraw()
    if time.monotonic() > _state["until"]:
        clear_highlight()
        return None
    return 0.04


def clear_highlight() -> None:
    handle = _state["handle"]
    if handle is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, "WINDOW")
        except (ValueError, RuntimeError):
            pass
    _state.update(handle=None, object=None, timer=False)
    for area in _viewports():
        area.tag_redraw()


def highlight_object(ref: str, style: str, duration_ms: int) -> dict:
    if bpy.app.background:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "there is no 3D viewport when Blender runs in the background")
    mod = refs.parse_modifier_ref(ref)
    obj_name = mod[0] if mod else refs.parse_object_ref(ref)
    obj = bpy.data.objects.get(obj_name) if obj_name else None
    if obj is None:
        raise WyspError(ErrorCode.TARGET_NOT_FOUND, f"cannot highlight {ref}")
    if _state["broken"]:
        raise WyspError(ErrorCode.NOT_SUPPORTED, "highlight drawing is disabled after an earlier error")
    if mod:
        from .actions.show_properties_tab import switch_tab

        switch_tab("MODIFIER")
    _state["object"] = obj.name
    _state["until"] = time.monotonic() + duration_ms / 1000.0
    if _state["handle"] is None:
        _state["handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    if not _state["timer"]:
        _state["timer"] = True
        bpy.app.timers.register(_tick, first_interval=0.02)
    return {"ok": True}
