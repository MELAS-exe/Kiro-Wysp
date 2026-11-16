import type { HelloResult, Manifest } from "./generated/index";
import { ErrorCode, WyspError } from "./errors";

/** The subset of the browser WebSocket the client uses (injectable for tests). */
export interface WebSocketLike {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: unknown) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

export type ClientStatus = "stopped" | "connecting" | "connected" | "disconnected" | "refused";

export type RequestHandler = (method: string, params: Record<string, unknown>) => Promise<unknown> | unknown;

export interface AdapterClientOptions {
  manifest: Manifest;
  /** ws://127.0.0.1:8765/ws/adapter */
  url: string;
  /** Pairing token from ~/.wysp/token. Never logged. */
  token: string;
  handler: RequestHandler;
  /** Heartbeat period in ms. The contract requires one at least every 20 s. */
  heartbeatMs?: number;
  /** Backoff bounds in ms for reconnection. */
  backoffMinMs?: number;
  backoffMaxMs?: number;
  onStatus?: (status: ClientStatus, detail?: string) => void;
  /** Included in heartbeats. */
  stateVersion?: () => number | undefined;
  socketFactory?: (url: string) => WebSocketLike;
}

const HELLO_ID = "hello-1";

/**
 * WebSocket JSON-RPC client that connects an adapter to Wysp Core. It is meant to live in an MV3 service
 * worker: it keeps no state that cannot be rebuilt (a restarted worker just creates a new client, which
 * reconnects and sends `wysp.hello` again).
 */
export class AdapterClient {
  status: ClientStatus = "stopped";
  sessionId: string | null = null;
  lastError: string | null = null;

  private readonly opts: Required<Pick<AdapterClientOptions, "heartbeatMs" | "backoffMinMs" | "backoffMaxMs">> &
    AdapterClientOptions;
  private ws: WebSocketLike | null = null;
  private stopped = true;
  private backoff: number;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(options: AdapterClientOptions) {
    this.opts = { heartbeatMs: 15_000, backoffMinMs: 500, backoffMaxMs: 10_000, ...options };
    this.backoff = this.opts.backoffMinMs;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimers();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      try {
        ws.send(JSON.stringify({ jsonrpc: "2.0", method: "wysp.bye", params: { reason: "stop" } }));
        ws.close(1000, "stop");
      } catch {
        /* best effort */
      }
    }
    this.setStatus("stopped");
  }

  get connected(): boolean {
    return this.status === "connected";
  }

  /** Send a notification (no response expected). Returns false when not connected. */
  notify(method: string, params?: Record<string, unknown>): boolean {
    if (!this.ws || !this.connected) return false;
    return this.send(params === undefined ? { jsonrpc: "2.0", method } : { jsonrpc: "2.0", method, params });
  }

  // ------------------------------------------------------------------------------------ internals
  private setStatus(status: ClientStatus, detail?: string): void {
    if (status === this.status && detail === undefined) return;
    this.status = status;
    this.opts.onStatus?.(status, detail);
  }

  private send(message: unknown): boolean {
    const ws = this.ws;
    if (!ws) return false;
    try {
      ws.send(JSON.stringify(message));
      return true;
    } catch {
      return false;
    }
  }

  private clearTimers(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
  }

  private connect(): void {
    if (this.stopped) return;
    this.setStatus("connecting");
    let ws: WebSocketLike;
    try {
      ws = this.opts.socketFactory ? this.opts.socketFactory(this.opts.url) : (new WebSocket(this.opts.url) as unknown as WebSocketLike);
    } catch (err) {
      this.lastError = `cannot open socket: ${(err as Error).message}`;
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.send({
        jsonrpc: "2.0",
        id: HELLO_ID,
        method: "wysp.hello",
        params: { manifest: this.opts.manifest, token: this.opts.token },
      });
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") void this.onMessage(ev.data);
    };
    ws.onerror = () => {
      this.lastError = "cannot reach Core";
    };
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.sessionId = null;
      this.clearTimers();
      if (this.status !== "refused") this.setStatus("disconnected", this.lastError ?? undefined);
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, this.opts.backoffMaxMs);
  }

  private startHeartbeat(): void {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = setInterval(() => {
      const sv = this.opts.stateVersion?.();
      this.notify("wysp.heartbeat", sv === undefined ? {} : { state_version: sv });
    }, this.opts.heartbeatMs);
  }

  private async onMessage(raw: string): Promise<void> {
    let msg: Record<string, unknown>;
    try {
      msg = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return;
    }
    if (typeof msg.method === "string") {
      await this.onRequest(msg.method, (msg.params as Record<string, unknown> | undefined) ?? {}, msg.id);
      return;
    }
    if (msg.id === HELLO_ID) {
      const error = msg.error as { code?: number; message?: string } | undefined;
      if (error) {
        this.lastError = `hello refused (${error.code}): ${error.message}`;
        this.setStatus("refused", this.lastError);
        // Do not hammer the Core with a wrong token: stay at the maximum backoff.
        this.backoff = this.opts.backoffMaxMs;
        this.ws?.close(1000, "refused");
        return;
      }
      const result = msg.result as HelloResult | undefined;
      this.sessionId = result?.session_id ?? null;
      this.lastError = null;
      this.backoff = this.opts.backoffMinMs;
      const interval = Math.max(1, (result?.heartbeat_interval_s ?? 20) * 1000);
      this.opts.heartbeatMs = Math.min(this.opts.heartbeatMs, interval);
      this.setStatus("connected");
      this.startHeartbeat();
    }
  }

  private async onRequest(method: string, params: Record<string, unknown>, id: unknown): Promise<void> {
    try {
      const result = await this.opts.handler(method, params);
      if (id !== undefined && id !== null) this.send({ jsonrpc: "2.0", id, result: result ?? null });
    } catch (err) {
      if (id === undefined || id === null) return;
      const error =
        err instanceof WyspError
          ? err.toJSON()
          : { code: ErrorCode.EXECUTION_FAILED, message: err instanceof Error ? err.message : "execution failed" };
      this.send({ jsonrpc: "2.0", id, error });
    }
  }
}
