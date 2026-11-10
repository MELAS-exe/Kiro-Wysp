"""Highlight things inside Blender: a 3D object, or a piece of the interface. Never changes scene data.

* Objects: a pulsing bounding box in the 3D viewport.
* Interface elements (``blender://ui/...``, see ``ui_targets``): a pulsing frame around the region plus a
  callout. Properties tabs and the viewport gizmo also get an estimated marker, because Blender's API does
  not expose button rectangles. The frame is exact, the marker is approximate, and the callout says what to find.
* Labels (``blender://ui/label/<AREA>/<text>``): hybrid native + visual. Blender knows where each editor is but
  not where its buttons are, so the editor is screenshotted (``screen.screenshot_area``), the Core's local OCR
  (``POST /api/ocr``) says where the words are, and the matching words get a frame. The screenshot is sent to
  the local Core only and deleted at once.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import time
import urllib.error
import urllib.request

import bpy
from wysp_adapter_sdk import ErrorCode, WyspError

from . import label_match, nav_detect, refs, telemetry, ui_targets

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
    "label_rect": None,  # (x, y, w, h) in window pixels, origin bottom-left
    "tab_rect": None,  # same, for a Properties tab found on a screenshot
}
_core: dict = {"http": None}  # http://host:port of the Core, set when the adapter connects
OCR_TIMEOUT_S = 0.8  # the Core waits 1.5 s for a highlight in total (0.5 s budget + 1 s slack)
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


MEASURED_AT_SCALE = 1.5  # the pixel constants below were measured at this effective UI scale (Blender 5.2)


def _ui_scale() -> float:
    """Factor for the measured pixel constants.

    `preferences.system.ui_scale` is the effective scale: the Resolution Scale preference times the monitor
    DPI, which is what Blender sizes its widgets with.
    """
    return float(bpy.context.preferences.system.ui_scale) / MEASURED_AT_SCALE


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
    unit = 20 * s * MEASURED_AT_SCALE  # Blender's UI unit in pixels
    pitch = 1.8 * unit - 14  # fitted at two scales; only a fallback when the screenshot cannot be read
    y = region_height - 10 * s
    first_object = next((t for t in tabs if t in ui_targets.OBJECT_LEVEL_TABS), None)
    for t in tabs:
        if t in ("RENDER", first_object) and t != tabs[0]:
            y -= 0.4 * unit
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
            if target.text is not None:
                _draw_label(area, region, target, s, alpha)
                continue
            outlined = (not target.regions and region.type in _ALL_REGIONS) or (
                region.type in target.regions and not target.gizmo
            )
            if outlined:
                inset = 3.0
                _draw_lines(_rect_lines(inset, inset, region.width - 2 * inset, region.height - 2 * inset), 4.0, alpha)
            if target.tab and region.type == "NAVIGATION_BAR":
                seen = _state["tab_rect"]
                if seen is not None:
                    rect = (seen[0] - region.x, seen[1] - region.y, seen[2], seen[3])
                else:
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


def _draw_label(area, region, target, s: float, alpha: float) -> None:
    rect = _state["label_rect"]
    if rect is None:  # not located (no OCR): frame the editor and say what to look for
        if region.type == "WINDOW":
            inset = 3.0
            _draw_lines(_rect_lines(inset, inset, region.width - 2 * inset, region.height - 2 * inset), 4.0, alpha)
            _draw_callout(region, f"Look for {target.label}", top=region.height - _overlap_top(area, region) - 8 * s)
        return
    pad = 5 * s
    x, y, w, h = rect[0] - region.x - pad, rect[1] - region.y - pad, rect[2] + 2 * pad, rect[3] + 2 * pad
    if x + w < 0 or y + h < 0 or x > region.width or y > region.height:
        return  # not in this region
    _fill_rect(x, y, w, h, (*COLOR, 0.18 * alpha))
    _draw_lines(_rect_lines(x, y, w, h), 3.0, 1.0)
    # No name tag: the frame sits on the text itself, and a tag would cover the neighbouring controls.


def set_core_url(adapter_url: str) -> None:
    """Remember the Core's HTTP address (derived from the adapter WebSocket URL) for OCR requests."""
    base = adapter_url.rsplit("/ws/", 1)[0] if "/ws/" in adapter_url else adapter_url.rstrip("/")
    if base.startswith("wss://"):
        base = "https://" + base[len("wss://") :]
    elif base.startswith("ws://"):
        base = "http://" + base[len("ws://") :]
    _core["http"] = base


def _window_of(area):
    return next(w for w in bpy.context.window_manager.windows if area in w.screen.areas[:])


def _shoot(area) -> str:
    """Screenshot one editor to a temporary PNG (main thread). The caller deletes the file.

    Do not force a redraw first (``wm.redraw_timer`` with a buffer swap): the capture then reads an empty
    buffer. An older Wysp frame may still be in the picture; it is thin and faint, and both the OCR match
    and the icon detection ignore it.
    """
    win = _window_of(area)
    region = next((r for r in area.regions if r.type == "WINDOW"), area.regions[0])
    fd, path = tempfile.mkstemp(prefix="wysp-ui-", suffix=".png")
    os.close(fd)
    with bpy.context.temp_override(window=win, screen=win.screen, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=path)
    debug_dir = os.environ.get("WYSP_DEBUG_SHOTS")  # developer switch: keep what Wysp looked at
    if debug_dir:
        import shutil

        os.makedirs(debug_dir, exist_ok=True)
        shutil.copy(path, os.path.join(debug_dir, f"{time.strftime('%H%M%S')}-{area.type}-{os.path.basename(path)}"))
    return path


def _forget(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _screenshot_area(area) -> bytes:
    """PNG bytes of one editor. The temporary file is deleted before returning."""
    path = _shoot(area)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        _forget(path)


def _detect_tab(area, tabs: list[str], tab: str):
    """Window rect of `tab`'s icon in the tab column, read from a screenshot; None when unsure."""
    nav = next((r for r in area.regions if r.type == "NAVIGATION_BAR"), None)
    if nav is None or tab not in tabs:
        return None
    started = time.monotonic()
    path = _shoot(area)
    image = None
    try:
        import numpy as np

        image = bpy.data.images.load(path, check_existing=False)
        w, h = image.size
        if (w, h) != (area.width, area.height):
            return None
        px = np.empty(w * h * 4, dtype=np.float32)
        image.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)  # rows bottom-up, as Blender stores images
        x0, x1 = nav.x - area.x + 6, nav.x - area.x + nav.width - 6
        y0, y1 = nav.y - area.y, nav.y - area.y + nav.height
        if x1 - x0 < 6 or y1 - y0 < 20:
            return None
        crop = px[y0:y1, x0:x1, :3]
        lum = (crop[..., 0] * 0.3 + crop[..., 1] * 0.59 + crop[..., 2] * 0.11)[::-1, ::2]  # top row first
        boxes = nav_detect.tab_boxes(nav_detect.icon_runs(lum.tolist()), len(tabs))
        index = tabs.index(tab)
        telemetry.tm.emit(
            "highlight.tab",
            ok=bool(boxes) and index < len(boxes),
            icons=len(boxes or []),
            tabs=len(tabs),
            ms=round((time.monotonic() - started) * 1000, 1),
        )
        if boxes and index >= len(boxes) and len(boxes) >= index * 0.5:
            return "below"  # the column is cut off: this tab is under its visible part
        if not boxes or index >= len(boxes):
            return None
        top, bottom = boxes[index]
        return (nav.x + 2.0, nav.y + nav.height - 1.0 - bottom, nav.width - 4.0, float(bottom - top + 1))
    except Exception:  # noqa: BLE001 - fall back to the estimate rather than fail the highlight
        log.debug("tab detection failed", exc_info=True)
        return None
    finally:
        if image is not None:
            bpy.data.images.remove(image)
        _forget(path)


def _recognize(png: bytes) -> dict:
    if not _core["http"]:
        raise RuntimeError("not connected to a Core")
    req = urllib.request.Request(_core["http"] + "/api/ocr", data=png, headers={"Content-Type": "image/png"})
    with urllib.request.urlopen(req, timeout=OCR_TIMEOUT_S) as resp:  # noqa: S310 - the local Core only
        return json.loads(resp.read().decode("utf-8"))


def _spellings(text: str) -> list[str]:
    """The label as written, plus Blender's UI name when the tutor used a property identifier (``segments``)."""
    names = [text]
    obj = bpy.context.view_layer.objects.active
    owners = [obj, *obj.modifiers] if obj is not None else []
    for owner in owners:
        prop = owner.bl_rna.properties.get(text)
        if prop is not None and prop.name and prop.name not in names:
            names.append(prop.name)
    return names


def _locate(area, text: str) -> tuple[tuple[float, float, float, float] | None, dict]:
    """Find `text` on a screenshot of `area`. Returns (window rect or None, details for the tutor)."""
    started = time.monotonic()
    png = _screenshot_area(area)
    shot_ms = (time.monotonic() - started) * 1000
    try:
        result = _recognize(png)
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError, OSError) as exc:
        telemetry.tm.emit("highlight.label", ok=False, reason="ocr_unavailable", shot_ms=round(shot_ms, 1))
        return None, {"located": False, "reason": f"text recognition unavailable ({type(exc).__name__})"}
    lines = result.get("lines", [])
    match, ties = label_match.find(_spellings(text), lines)
    total_ms = (time.monotonic() - started) * 1000
    telemetry.tm.emit(
        "highlight.label",
        ok=match is not None,
        shot_ms=round(shot_ms, 1),
        ocr_ms=result.get("ms"),
        total_ms=round(total_ms, 1),
        lines=len(lines),
        score=match.score if match else None,
        ties=ties,
        full={"wanted": text, "seen": match.text if match else None},
    )
    if match is None:
        visible = label_match.visible_labels(lines)
        cut = sum(1 for line in lines if str(line.get("text", "")).rstrip().endswith(("...", "…")))
        return None, {"located": False, "visible": visible, "too_narrow": cut >= max(3, len(lines) // 3)}
    # Image pixels (origin top-left) -> window pixels (origin bottom-left). The screenshot is the area's size;
    # scale anyway in case a platform captures at another resolution.
    sx = area.width / float(result.get("width") or area.width)
    sy = area.height / float(result.get("height") or area.height)
    x = area.x + match.x * sx
    y = area.y + area.height - (match.y + match.h) * sy
    details = {"located": True, "seen": match.text, "confidence": match.score}
    if ties > 1:
        details["note"] = f"{ties} places show this text; the first one is marked"
    return (x, y, match.w * sx, match.h * sy), details


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
    _state.update(
        object=None,
        object_handle=None,
        ui=[],
        handlers=[],
        handles={},
        timer=False,
        drawn=set(),
        label_rect=None,
        tab_rect=None,
    )
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
    if target.text is not None:
        return _highlight_label(target, duration_ms)
    _state["tab_rect"] = None
    if target.tab:
        _state["tabs"] = _probe_tabs()
        from .actions.show_properties_tab import switch_tab

        if not switch_tab(target.tab):
            raise WyspError(
                ErrorCode.PRECONDITION_FAILED, f"the {target.tab} tab is not available for the active object"
            )
        _state["ui"] = []
        props = [a for a in _areas() if a.type == "PROPERTIES"]
        if props:
            _state["tab_rect"] = _detect_tab(max(props, key=lambda a: a.width * a.height), _state["tabs"], target.tab)
    note = None
    if _state["tab_rect"] == "below":
        _state["tab_rect"] = None
        note = "the tab is open, but its icon is below the visible part of the tab column (the user can scroll it)"
    _state["object"] = None
    _state["ui"] = [target]
    _register_ui_handlers([target])
    _start(duration_ms)
    out = {"ok": True, "note": target.label}
    if note:
        out["warning"] = note
    return out


def _highlight_label(target, duration_ms: int) -> dict:
    areas = [a for a in _areas() if a.ui_type == target.area or a.type == target.area]
    area = max(areas, key=lambda a: a.width * a.height)
    _state["object"] = None
    _state["label_rect"] = None
    _state["ui"] = []  # do not photograph an older highlight
    rect, details = _locate(area, target.text)
    if rect is None and details.get("visible") is not None:
        shown = ", ".join(details["visible"][:25]) or "no readable text"
        why = (
            "the editor is too narrow: Blender shortened its labels; ask the user to widen it"
            if details.get("too_narrow")
            else "it may be scrolled away, collapsed or in another tab"
        )
        raise WyspError(
            ErrorCode.TARGET_NOT_FOUND,
            f"{target.label} is not visible in the {ui_targets.AREAS.get(target.area, (target.area,))[0]} right now "
            f"({why}). Visible labels: {shown}",
        )
    _state["label_rect"] = rect
    _state["ui"] = [target]
    _register_ui_handlers([target])
    _start(duration_ms)
    return {"ok": True, "note": target.label, **details}


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
            props = [a for a in _areas() if a.type == "PROPERTIES"]
            if props:
                area = max(props, key=lambda a: a.width * a.height)
                found = _detect_tab(area, _state["tabs"], "MODIFIER")
                _state["tab_rect"] = None if found == "below" else found
            _state["ui"] = [tab]
            _register_ui_handlers([tab])
    if _state.get("object_handle") is None:
        _state["object_handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw_object, (), "WINDOW", "POST_VIEW")
    _start(duration_ms)
    return {"ok": True}


# Backwards-compatible name used by earlier code and tests.
highlight_object = highlight

# Public name for other modules of the add-on (the approval banner).
draw_callout = _draw_callout
