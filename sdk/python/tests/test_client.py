"""Python SDK against a local Core stand-in (a WebSocket server in a thread) [adapter-contract 7.1].

Covers: hello order, request routing, error mapping, dispatcher ordering, timing reports (the data the Core's
time budgets are checked against), heartbeat and reconnect with a second hello. `websockets` is a test-only
dependency here (the SDK itself uses websocket-client).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest
from websockets.sync.server import serve
from wysp_adapter_sdk import AdapterClient, ErrorCode, QueueDispatcher, WyspError

MANIFEST = {"adapter_id": "t", "contract_version": "1.1.0"}


class FakeCore:
    """Accepts adapters, records every message, answers hello, and lets a test push requests."""

    def __init__(self, heartbeat_interval_s: float = 20.0) -> None:
        self.heartbeat_interval_s = heartbeat_interval_s
        self.received: list[dict[str, Any]] = []
        self.connections: list[Any] = []
        self.lock = threading.Lock()
        self.server = serve(self._handle, "127.0.0.1", 0, close_timeout=0.2)
        self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handle(self, ws) -> None:
        with self.lock:
            self.connections.append(ws)
        try:
            for raw in ws:
                msg = json.loads(raw)
                with self.lock:
                    self.received.append(msg)
                if msg.get("method") == "wysp.hello":
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": msg["id"],
                                "result": {
                                    "session_id": f"s{len(self.connections)}",
                                    "contract_version": "1.1.0",
                                    "core_version": "test",
                                    "heartbeat_interval_s": self.heartbeat_interval_s,
                                },
                            }
                        )
                    )
        except Exception:  # noqa: BLE001 - the client went away
            pass

    def send(self, message: dict[str, Any], connection: int = -1) -> None:
        self.connections[connection].send(json.dumps(message))

    def request(self, id_: Any, method: str, params: dict[str, Any] | None = None, connection: int = -1) -> None:
        self.send({"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}, connection)

    def drop(self, connection: int = -1) -> None:
        self.connections[connection].close()

    def messages(self, **match: Any) -> list[dict[str, Any]]:
        with self.lock:
            return [m for m in self.received if all(m.get(k) == v for k, v in match.items())]

    def wait(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("timeout")

    def response(self, id_: Any) -> dict[str, Any]:
        self.wait(lambda: any(m.get("id") == id_ and "method" not in m for m in self.received))
        return next(m for m in self.messages(id=id_) if "method" not in m)

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def core():
    c = FakeCore()
    yield c
    c.close()


def start(core: FakeCore, handler, **kwargs) -> AdapterClient:
    client = AdapterClient(MANIFEST, core.url, "tok", handler, **kwargs)
    client.start()
    core.wait(lambda: client.connected)
    return client


def test_hello_is_the_first_message_and_carries_manifest_and_token(core) -> None:
    client = start(core, lambda m, p: {})
    try:
        first = core.received[0]
        assert first["method"] == "wysp.hello" and first["id"]
        assert first["params"] == {"manifest": MANIFEST, "token": "tok"}
        assert client.session_id == "s1"
    finally:
        client.stop()


def test_requests_are_routed_to_the_handler_and_answered_with_their_id(core) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(method: str, params: dict) -> Any:
        seen.append((method, params))
        return {"echo": params}

    client = start(core, handler)
    try:
        core.request(7, "adapter.observe", {"scope": {"level": "full"}})
        core.request("abc", "adapter.get_context")
        assert core.response(7)["result"] == {"echo": {"scope": {"level": "full"}}}
        assert core.response("abc")["result"] == {"echo": {}}
        assert [m for m, _ in seen] == ["adapter.observe", "adapter.get_context"]
    finally:
        client.stop()


def test_errors_are_mapped_to_contract_error_objects(core) -> None:
    def handler(method: str, params: dict) -> Any:
        if method == "adapter.undo":
            raise WyspError(ErrorCode.UNDO_UNAVAILABLE, "gone", {"token": "x"})
        raise RuntimeError("boom")  # a bug in the adapter, never a stack trace on the wire

    client = start(core, handler)
    try:
        core.request(1, "adapter.undo", {"token": "x"})
        core.request(2, "adapter.execute")
        assert core.response(1)["error"] == {"code": -32015, "message": "gone", "data": {"token": "x"}}
        err = core.response(2)["error"]
        assert err["code"] == int(ErrorCode.EXECUTION_FAILED) and err["message"] == "RuntimeError: boom"
        assert "Traceback" not in json.dumps(err)
    finally:
        client.stop()


def test_notifications_from_the_core_get_no_response(core) -> None:
    seen: list[str] = []
    client = start(core, lambda m, p: seen.append(m))
    try:
        core.send({"jsonrpc": "2.0", "method": "adapter.highlight", "params": {}})
        core.request(9, "adapter.get_actions")
        core.response(9)
        assert seen == ["adapter.highlight", "adapter.get_actions"]
        assert [m for m in core.received if m.get("id") is None and "result" in m] == []
    finally:
        client.stop()


def test_queue_dispatcher_keeps_request_order_and_runs_on_the_pumping_thread(core) -> None:
    order: list[tuple[int, str]] = []
    dispatcher = QueueDispatcher()

    def handler(method: str, params: dict) -> Any:
        order.append((params["n"], threading.current_thread().name))
        return {"n": params["n"]}

    client = start(core, handler, dispatcher=dispatcher)
    try:
        for n in range(5):
            core.request(100 + n, "adapter.get_context", {"n": n})
        core.wait(lambda: dispatcher.pending() == 5)
        assert order == [], "nothing runs until the host thread pumps"
        pumped = 0
        while pumped < 5:
            pumped += dispatcher.pump(budget_s=1.0)
        assert [n for n, _ in order] == [0, 1, 2, 3, 4]
        assert {t for _, t in order} == {threading.current_thread().name}
        assert [core.response(100 + n)["result"]["n"] for n in range(5)] == [0, 1, 2, 3, 4]
    finally:
        client.stop()


def test_request_timing_is_reported_for_budget_checks(core) -> None:
    reports: list[dict] = []

    def handler(method: str, params: dict) -> Any:
        time.sleep(0.05)
        if params.get("fail"):
            raise WyspError(ErrorCode.TARGET_NOT_FOUND, "no")
        return {}

    client = start(core, handler, on_request_done=reports.append)
    try:
        core.request(1, "adapter.observe")
        core.request(2, "adapter.execute", {"fail": True})
        core.response(1), core.response(2)
        core.wait(lambda: len(reports) == 2)
        ok, failed = sorted(reports, key=lambda r: r["method"])[0], sorted(reports, key=lambda r: r["method"])[1]
        assert ok["method"] == "adapter.execute" and ok["ok"] is False and ok["error_code"] == -32012
        assert failed["method"] == "adapter.observe" and failed["ok"] is True and failed["error_code"] is None
        assert all(r["run_ms"] >= 45 and r["queue_ms"] >= 0 for r in reports)
    finally:
        client.stop()


def test_heartbeat_follows_the_interval_the_core_asks_for() -> None:
    core = FakeCore(heartbeat_interval_s=0.2)
    client = start(core, lambda m, p: {}, heartbeat_s=15.0, state_version=lambda: 42)
    try:
        assert client.heartbeat_s == pytest.approx(0.2)  # the smaller of the two wins
        core.wait(lambda: len(core.messages(method="wysp.heartbeat")) >= 2)
        beats = core.messages(method="wysp.heartbeat")
        assert all(b["params"] == {"state_version": 42} and "id" not in b for b in beats)
    finally:
        client.stop()
        core.close()


def test_the_client_reconnects_and_says_hello_again(core) -> None:
    client = start(core, lambda m, p: {"ok": True})
    try:
        core.drop()
        core.wait(lambda: len(core.messages(method="wysp.hello")) == 2 and client.connected, timeout=10)
        assert client.session_id == "s2"
        core.request(5, "adapter.get_context")
        assert core.response(5)["result"] == {"ok": True}
    finally:
        client.stop()


def test_a_refused_hello_stops_the_session_and_reports_why(core) -> None:
    client = AdapterClient(MANIFEST, core.url, "wrong", lambda m, p: {})
    client.start()
    try:
        core.wait(lambda: core.messages(method="wysp.hello"))
        core.send({"jsonrpc": "2.0", "id": core.received[0]["id"], "error": {"code": -32019, "message": "bad token"}})
        core.wait(lambda: client.last_error is not None and "-32019" in client.last_error)
    finally:
        client.stop()
