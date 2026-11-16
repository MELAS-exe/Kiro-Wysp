"""The action catalog: one module per action; each defines spec() and run(params, dry_run)."""

from __future__ import annotations

from . import (
    add_modifier,
    apply_modifier,
    assign_material,
    move_modifier,
    remove_modifier,
    select_object,
    set_modifier_property,
    set_object_transform,
    show_properties_tab,
    toggle_modifier_visibility,
)

ALL = [
    select_object,
    show_properties_tab,
    set_object_transform,
    add_modifier,
    set_modifier_property,
    move_modifier,
    toggle_modifier_visibility,
    assign_material,
    remove_modifier,
    apply_modifier,
]


def register_all(registry) -> None:
    for module in ALL:
        registry.register(module.spec(), module.run)
