// Panel state. Components only render this store and send protocol messages: no tutoring logic here.
import { create } from "zustand";
import { applyPatch, emptyBoard } from "./board/applyOps";
import { preferredAdapter } from "./coreVoice";
import { CoreSocket, coreUrl } from "./protocol";
import type { AdapterInfo, Board, CoreMessage, ExploreState, LogLevel, PanelMessage, PermissionRequest, Segment } from "./protocol";

// queued: not spoken yet (hidden); skipped: cancelled before it was spoken (hidden, Continue replays it).
export type SegState = "queued" | "playing" | "played" | "cancelled" | "skipped";

export type TranscriptItem =
  | { kind: "user"; id: string; text: string; source: string }
  | { kind: "wysp"; id: string; segment: Segment; state: SegState }
  | { kind: "evidence"; id: string; title: string; scope: string; ok: boolean }
  | { kind: "note"; id: string; text: string; tone: "info" | "error" };

export interface SessionInfo {
  session_id: string;
  lang: string;
  active_adapter: string | null;
  llm: string;
  model: string | null;
  profile: string | null;
  logging: LogLevel | null;
  logPath: string | null;
}

interface PanelState {
  connected: boolean;
  session: SessionInfo | null;
  adapters: AdapterInfo[];
  board: Board;
  status: "idle" | "thinking" | "acting" | "speaking";
  activity: string;
  transcript: TranscriptItem[];
  queue: Segment[];
  current: Segment | null;
  permission: PermissionRequest | null;
  clarification: { question: string; options: string[] } | null;
  voiceOn: boolean;
  listening: boolean;
  interim: string;
  selectedNode: string | null;
  // One thing fills the panel at a time: the conversation or the diagram.
  view: "chat" | "board";
  explore: ExploreState | null;

  handle: (m: CoreMessage) => void;
  send: (m: PanelMessage) => boolean;
  setVoiceOn: (on: boolean) => void;
  setListening: (on: boolean, interim?: string) => void;
  setCurrent: (s: Segment | null) => void;
  popQueue: () => Segment | undefined;
  markSegment: (id: string, state: SegState) => void;
  cancelNarration: (fromIndex?: number) => void;
  addUser: (text: string, source: string) => void;
  setSelected: (id: string | null) => void;
  setView: (v: "chat" | "board") => void;
  dismissPermission: () => void;
  dismissClarification: () => void;
}

let socket: CoreSocket | null = null;
let counter = 0;
const nextId = (p: string) => `${p}${++counter}`;

let asked = false; // the host's preferred adapter is requested once per page load
export const useStore = create<PanelState>((set, get) => ({
  connected: false,
  session: null,
  adapters: [],
  board: emptyBoard(),
  status: "idle",
  activity: "",
  transcript: [],
  queue: [],
  current: null,
  permission: null,
  clarification: null,
  voiceOn: true,
  listening: false,
  interim: "",
  selectedNode: null,
  view: "chat",
  explore: null,

  send: (m) => socket?.send(m) ?? false,
  setVoiceOn: (on) => set({ voiceOn: on }),
  setListening: (on, interim = "") => set({ listening: on, interim }),
  setCurrent: (s) => set({ current: s }),
  popQueue: () => {
    const [first, ...rest] = get().queue;
    if (first) set({ queue: rest });
    return first;
  },
  markSegment: (id, state) =>
    set((s) => ({ transcript: s.transcript.map((t) => (t.kind === "wysp" && t.segment.id === id ? { ...t, state } : t)) })),
  cancelNarration: (fromIndex) =>
    set((s) => ({
      queue: [],
      current: null,
      transcript: s.transcript.map((t) =>
        t.kind === "wysp" && (t.state === "queued" || t.state === "playing") && (fromIndex === undefined || t.segment.index >= fromIndex)
          ? { ...t, state: t.state === "playing" ? ("cancelled" as const) : ("skipped" as const) }
          : t,
      ),
    })),
  // A new message from the user also dismisses any pending clarification question.
  addUser: (text, source) =>
    set((s) => ({ clarification: null, transcript: [...s.transcript, { kind: "user", id: nextId("u"), text, source }] })),
  setSelected: (id) => set({ selectedNode: id }),
  setView: (view) => set({ view }),
  dismissPermission: () => set({ permission: null }),
  dismissClarification: () => set({ clarification: null }),

  handle: (m) => {
    switch (m.type) {
      case "session.state":
        set({
          session: {
            session_id: m.session_id,
            lang: m.lang,
            active_adapter: m.active_adapter,
            llm: m.llm,
            model: m.model ?? null,
            profile: m.profile,
            logging: m.logging ?? null,
            logPath: m.log_path ?? null,
          },
        });
        break;
      case "adapters.list":
        set({ adapters: m.adapters });
        if (preferredAdapter && !asked && m.adapters.some((a) => a.adapter_id === preferredAdapter && a.connected)) {
          asked = true;
          if (get().session?.active_adapter !== preferredAdapter) get().send({ type: "adapter.activate", adapter_id: preferredAdapter });
        }
        break;
      case "status":
        set({ status: m.state, activity: m.state === "idle" ? "" : get().activity });
        break;
      case "activity":
        set({ activity: m.text });
        break;
      case "chat.user": {
        // Echo of a message sent from another Panel (or by "Why?"). Skip our own typed echo.
        const last = get().transcript[get().transcript.length - 1];
        if (!(last && last.kind === "user" && last.text === m.text)) get().addUser(m.text, m.source);
        else set({ clarification: null });
        break;
      }
      case "explore.state": {
        const { type: _t, ...state } = m;
        set({ explore: state });
        break;
      }
      case "board.snapshot":
        set({ board: m.board });
        break;
      case "board.patch": {
        const r = applyPatch(get().board, m.patch);
        if (r.ok) {
          // New elements appeared: show them. Updates to what is already there leave the view alone.
          const grew = r.board.nodes.length > get().board.nodes.length;
          set({ board: r.board, ...(grew ? { view: "board" as const } : {}) });
        }
        else if (r.reason === "gap") get().send({ type: "board.snapshot_request" });
        break;
      }
      case "narration.segment": {
        const segment = { ...m.segment, speaker: m.speaker !== false };
        set((s) => ({
          queue: [...s.queue, segment],
          transcript: [...s.transcript, { kind: "wysp", id: nextId("w"), segment, state: "queued" }],
        }));
        break;
      }
      case "narration.cancel":
        get().cancelNarration(m.from_index);
        break;
      case "clarification":
        set({ clarification: { question: m.question, options: m.options } });
        break;
      case "permission.request":
        set({ permission: m });
        break;
      case "permission.resolved":
        if (get().permission?.request_id === m.request_id) set({ permission: null });
        break;
      case "evidence.added":
        set((s) => ({
          transcript: [
            ...s.transcript,
            { kind: "evidence", id: nextId("e"), title: m.title, scope: m.scope, ok: m.evidence.outcomes.every((o) => o.ok) },
          ],
        }));
        break;
      case "error":
        set((s) => ({ transcript: [...s.transcript, { kind: "note", id: nextId("n"), text: m.message, tone: "error" }] }));
        break;
    }
  },
}));

export function connect(): () => void {
  const { handle } = useStore.getState();
  socket = new CoreSocket(
    coreUrl(),
    handle,
    (connected) => useStore.setState({ connected, ...(connected ? {} : { status: "idle" as const }) }),
  );
  socket.start();
  return () => socket?.stop();
}
