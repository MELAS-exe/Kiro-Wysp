import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  AdapterClient,
  ErrorCode,
  WyspError,
  type Manifest,
  type RequestHandler,
  type WebSocketLike,
} from "../src/index";

class FakeSocket implements WebSocketLike {
  sent: Array<Record<string, unknown>> = [];
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  send(data: string): void {
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(): void {
    this.closed = true;
    this.onclose?.({});
  }
  receive(msg: unknown): void {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

const manifest = {
  adapter_id: "t",
  app: { name: "t", version: "1" },
  contract_version: "1.1.0",
  integration_level: "interface",
  ref_scheme: "web",
  capabilities: ["observe"],
  entity_kinds: [],
} as Manifest;

describe("AdapterClient", () => {
  let sockets: FakeSocket[];
  const make = (handler: RequestHandler = async () => ({ ok: true })) => {
    sockets = [];
    return new AdapterClient({
      manifest,
      url: "ws://127.0.0.1:8765/ws/adapter",
      token: "secret-token",
      handler,
      heartbeatMs: 15_000,
      socketFactory: () => {
        const s = new FakeSocket();
        sockets.push(s);
        return s;
      },
    });
  };
  const connect = (c: AdapterClient, hb = 20) => {
    c.start();
    const s = sockets.at(-1)!;
    s.onopen?.({});
    s.receive({
      jsonrpc: "2.0",
      id: "hello-1",
      result: {
        session_id: "s1",
        contract_version: "1.1.0",
        core_version: "x",
        heartbeat_interval_s: hb,
      },
    });
    return s;
  };

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sends hello with manifest and token, then is connected", () => {
    const c = make();
    const s = connect(c);
    expect(s.sent[0]).toMatchObject({
      method: "wysp.hello",
      params: { token: "secret-token" },
    });
    expect(c.status).toBe("connected");
    expect(c.sessionId).toBe("s1");
  });

  it("sends a heartbeat at least every 20 s", () => {
    const c = make();
    const s = connect(c);
    vi.advanceTimersByTime(20_000);
    expect(
      s.sent.filter((m) => m.method === "wysp.heartbeat").length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("answers requests and maps WyspError to a JSON-RPC error", async () => {
    const c = make(async (method) => {
      if (method === "adapter.observe") return { observation_id: "o" };
      throw new WyspError(ErrorCode.TARGET_NOT_FOUND, "nope", {
        candidates: [],
      });
    });
    const s = connect(c);
    s.receive({ jsonrpc: "2.0", id: 7, method: "adapter.observe", params: {} });
    s.receive({ jsonrpc: "2.0", id: 8, method: "adapter.execute", params: {} });
    await vi.advanceTimersByTimeAsync(1);
    expect(s.sent.find((m) => m.id === 7)).toMatchObject({
      result: { observation_id: "o" },
    });
    expect(s.sent.find((m) => m.id === 8)).toMatchObject({
      error: { code: -32012, data: { candidates: [] } },
    });
  });

  it("reconnects with backoff and sends hello again", () => {
    const c = make();
    const first = connect(c);
    first.close();
    expect(c.status).toBe("disconnected");
    vi.advanceTimersByTime(600);
    expect(sockets.length).toBe(2);
    sockets[1]!.onopen?.({});
    expect(sockets[1]!.sent[0]).toMatchObject({ method: "wysp.hello" });
  });

  it("goes to refused when hello fails", () => {
    const c = make();
    c.start();
    const s = sockets[0]!;
    s.onopen?.({});
    s.receive({
      jsonrpc: "2.0",
      id: "hello-1",
      error: { code: -32019, message: "bad token" },
    });
    expect(c.status).toBe("refused");
    expect(c.lastError).not.toContain("secret-token");
  });

  it("notify returns false when not connected", () => {
    const c = make();
    expect(c.notify("event.navigation", { url: "x" })).toBe(false);
  });
});
