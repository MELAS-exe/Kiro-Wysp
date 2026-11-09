// Wire types of the UI protocol (Core <-> Panel). Mirrors core/src/wysp_core/contract/ui.py and board/model.py.

export type LogLevel = "off" | "basic" | "full";
export type Provenance = "observed" | "inferred" | "illustrative";
export type Layout = "stack" | "tree" | "graph" | "sequence";
export type StepStatus = "pending" | "active" | "done" | "failed";

export interface BoardNode {
  id: string;
  ref: string | null;
  kind: string;
  label: string;
  provenance: Provenance;
  confidence: number;
  props_view: string[][];
  group: string | null;
  badges: string[];
  order: number | null;
}
export interface BoardEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  label: string | null;
  provenance: Provenance;
}
export interface Step {
  id: string;
  index: number;
  text: string;
  status: StepStatus;
  target: string | null;
}
export interface Annotation {
  id: string;
  target: string;
  text: string;
  provenance: Provenance;
}
export interface Board {
  version: number;
  layout: Layout;
  focus: string[];
  nodes: BoardNode[];
  edges: BoardEdge[];
  steps: Step[];
  annotations: Annotation[];
  stale: boolean;
}
export interface BoardPatch {
  base_version: number;
  version: number;
  ops: BoardOp[];
}
export type BoardOp =
  | { op: "add_node"; node: BoardNode }
  | { op: "remove_node"; id: string }
  | { op: "add_edge"; edge: BoardEdge }
  | { op: "remove_edge"; id: string }
  | { op: "set_layout"; layout: Layout }
  | { op: "set_focus"; ids: string[] }
  | { op: "set_steps"; steps: Step[] }
  | { op: "update_step"; id: string; status?: StepStatus; text?: string }
  | { op: "add_annotation"; annotation: Annotation }
  | { op: "remove_annotation"; id: string }
  | { op: "set_stale"; stale: boolean }
  | { op: "clear" };

export interface AdapterInfo {
  adapter_id: string;
  app: { name: string; version: string };
  integration_level: string;
  capabilities: string[];
  profile_id: string | null;
  connected: boolean;
}
export interface Cue {
  at_word: number;
  op: "focus" | "highlight";
  target: string;
}
export interface Segment {
  id: string;
  turn_id: string;
  index: number;
  text: string;
  marker: string | null;
  cues: Cue[];
}
export interface PermissionRequest {
  type: "permission.request";
  request_id: string;
  action_id: string;
  title: string;
  target: string | null;
  risk: string;
  reversible: boolean;
  rationale: string;
  preview: unknown;
  voice_allowed: boolean;
  can_grant: boolean;
  timeout_s: number;
}
export interface Evidence {
  id: string;
  type: "verified" | "answered" | "declared";
  outcomes: { ok: boolean; path?: string | null; actual?: unknown; expected?: unknown }[];
}

export type CoreMessage =
  | {
      type: "session.state";
      session_id: string;
      lang: string;
      active_adapter: string | null;
      llm: string;
      model?: string | null;
      profile: string | null;
      logging?: LogLevel;
      log_path?: string | null;
    }
  | { type: "adapters.list"; adapters: AdapterInfo[] }
  | { type: "status"; state: "idle" | "thinking" | "acting" | "speaking" }
  | { type: "activity"; text: string }
  | { type: "chat.user"; text: string; source: string }
  | { type: "board.snapshot"; board: Board }
  | { type: "board.patch"; patch: BoardPatch }
  | { type: "narration.segment"; segment: Segment }
  | { type: "narration.cancel"; turn_id: string; from_index: number }
  | { type: "clarification"; question: string; options: string[] }
  | PermissionRequest
  | { type: "permission.resolved"; request_id: string; approved: boolean; by: string }
  | { type: "evidence.added"; evidence: Evidence; title: string; scope: string }
  | { type: "error"; code: string; message: string };

export type PanelMessage =
  | { type: "user.message"; text: string; source: "typed" | "voice" }
  | { type: "user.interrupt" }
  | { type: "user.continue" }
  | { type: "permission.respond"; request_id: string; decision: "approve" | "deny" | "grant_lesson"; via: "click" | "voice" }
  | { type: "board.select"; node_id: string }
  | { type: "board.ask_why"; node_id: string }
  | { type: "narration.progress"; segment_id: string; played: boolean }
  | { type: "narration.cue"; segment_id: string; index: number }
  | { type: "adapter.activate"; adapter_id: string }
  | { type: "board.snapshot_request" }
  | { type: "undo.last" }
  | { type: "settings.update"; lang?: string; logging?: LogLevel };

/** WebSocket to the Core with automatic reconnection (exponential backoff, 5 s maximum). */
export class CoreSocket {
  private ws: WebSocket | null = null;
  private stopped = false;
  private backoff = 300;

  constructor(
    private url: string,
    private onMessage: (m: CoreMessage) => void,
    private onState: (connected: boolean) => void,
  ) {}

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close();
  }

  send(msg: PanelMessage): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  private open(): void {
    const ws = new WebSocket(this.url);
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 300;
      this.onState(true);
    };
    ws.onmessage = (ev) => {
      try {
        this.onMessage(JSON.parse(ev.data as string) as CoreMessage);
      } catch (err) {
        console.error("bad message from the Core", err);
      }
    };
    ws.onclose = () => {
      this.onState(false);
      if (!this.stopped) {
        setTimeout(() => this.open(), this.backoff);
        this.backoff = Math.min(this.backoff * 2, 5000);
      }
    };
    ws.onerror = () => ws.close();
  }
}

export function coreUrl(): string {
  const host = location.port === "5173" ? "127.0.0.1:8765" : location.host;
  return `ws://${host}/ws/ui`;
}
