"""The action catalog: one module per action; each defines spec() and run(params, dry_run)."""

from __future__ import annotations

from . import (
    add_modifier,
    apply_modifier,
    move_modifier,
    remove_modifier,
    select_object,
    set_modifier_property,
    set_object_transform,
    show_properties_tab,
)

ALL = [
    select_object,
    show_properties_tab,
    set_object_transform,
    add_modifier,
    set_modifier_property,
    move_modifier,
    remove_modifier,
    apply_modifier,
]


def register_all(registry) -> None:
    for module in ALL:
        registry.register(module.spec(), module.run)
