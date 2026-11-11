"""Deferred handler results: the response goes out when the deferred settles, from any thread."""

from __future__ import annotations

import threading

from wysp_adapter_sdk import Deferred, ImmediateDispatcher, QueueDispatcher


def test_queue_dispatcher_waits_for_a_deferred() -> None:
    got: list[tuple] = []
    d = Deferred()
    qd = QueueDispatcher()
    qd.submit(lambda: d, lambda result, exc: got.append((result, exc)))
    assert qd.pump() == 1 and got == [], "nothing is answered while the work is still running"
    t = threading.Thread(target=lambda: d.resolve({"ok": True}))
    t.start()
    t.join()
    assert got == [({"ok": True}, None)]
    d.resolve("again")
    assert len(got) == 1, "the first answer wins"


def test_settled_before_attach_and_rejection() -> None:
    got: list[tuple] = []
    d = Deferred()
    d.reject(ValueError("no"))
    ImmediateDispatcher().submit(lambda: d, lambda result, exc: got.append((result, type(exc))))
    assert got == [(None, ValueError)]


def test_plain_results_are_unchanged() -> None:
    got: list = []
    ImmediateDispatcher().submit(lambda: 42, lambda result, exc: got.append(result))
    assert got == [42]
