"""UI protocol (Panel to Core): the messages the Panel may send on /ws/ui.

Core to Panel messages are plain JSON objects with a `type` field; see ui_api/hub.py for builders:
session.state, adapters.list, status, activity, board.snapshot, board.patch, narration.segment,
narration.cancel, clarification, permission.request, permission.resolved, evidence.added,
chat.user, error.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserMessage(_Msg):
    type: Literal["user.message"]
    text: str = Field(min_length=1, max_length=4000)
    source: Literal["typed", "voice"] = "typed"


class UserInterrupt(_Msg):
    type: Literal["user.interrupt"]


class UserContinue(_Msg):
    type: Literal["user.continue"]


class PermissionRespond(_Msg):
    type: Literal["permission.respond"]
    request_id: str
    decision: Literal["approve", "deny", "grant_lesson"]
    via: Literal["click", "voice"] = "click"


class BoardSelect(_Msg):
    type: Literal["board.select"]
    node_id: str


class BoardAskWhy(_Msg):
    type: Literal["board.ask_why"]
    node_id: str


class NarrationProgress(_Msg):
    type: Literal["narration.progress"]
    segment_id: str
    played: bool = True


class NarrationCue(_Msg):
    type: Literal["narration.cue"]
    segment_id: str
    index: int = Field(ge=0)


class AdapterActivate(_Msg):
    type: Literal["adapter.activate"]
    adapter_id: str


class SnapshotRequest(_Msg):
    type: Literal["board.snapshot_request"]


class UndoLast(_Msg):
    type: Literal["undo.last"]


class SettingsUpdate(_Msg):
    type: Literal["settings.update"]
    lang: str | None = Field(default=None, max_length=8)
    logging: Literal["off", "basic", "full"] | None = None


UiInbound = Annotated[
    Union[  # noqa: UP007
        UserMessage,
        UserInterrupt,
        UserContinue,
        PermissionRespond,
        BoardSelect,
        BoardAskWhy,
        NarrationProgress,
        NarrationCue,
        AdapterActivate,
        SnapshotRequest,
        UndoLast,
        SettingsUpdate,
    ],
    Field(discriminator="type"),
]

inbound_adapter: TypeAdapter[UiInbound] = TypeAdapter(UiInbound)
