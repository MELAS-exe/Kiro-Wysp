// PAN-P4: segments start in order, never overlap, and nothing of a cancelled turn plays after the cancel.
// Voice off: captions-only playback on fake timers (no speechSynthesis, no Audio).
import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CoreMessage, PanelMessage } from "./protocol";
import {
  interruptNarration,
  startNarrationPlayer,
  stopSpeech,
} from "./narration";
import { useStore } from "./store";

vi.mock("./coreVoice", () => ({
  coreHasNeuralVoice: async () => false,
  coreSpeak: async () => null,
}));

type Op =
  | { kind: "arrive"; chars: number; cue: boolean }
  | { kind: "advance"; ms: number }
  | { kind: "cancel" }
  | { kind: "interrupt" };

const opArb: fc.Arbitrary<Op> = fc.oneof(
  {
    weight: 4,
    arbitrary: fc.record({
      kind: fc.constant("arrive" as const),
      chars: fc.integer({ min: 0, max: 120 }),
      cue: fc.boolean(),
    }),
  },
  {
    weight: 4,
    arbitrary: fc.record({
      kind: fc.constant("advance" as const),
      ms: fc.integer({ min: 0, max: 6000 }),
    }),
  },
  { weight: 1, arbitrary: fc.constant({ kind: "cancel" as const }) },
  { weight: 1, arbitrary: fc.constant({ kind: "interrupt" as const }) },
);

let stopPlayer: () => void;
let sent: PanelMessage[];

function reset(): void {
  stopSpeech();
  sent = [];
  useStore.setState({
    queue: [],
    current: null,
    transcript: [],
    voiceOn: false,
    send: (m: PanelMessage) => (sent.push(m), true),
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  reset();
  stopPlayer = startNarrationPlayer();
});
afterEach(() => {
  stopPlayer();
  vi.useRealTimers();
});

describe("narration player", () => {
  it("prop: segments start in order, never overlap, and a cancelled turn never plays after the cancel (PAN-P4)", () => {
    fc.assert(
      fc.property(fc.array(opArb, { maxLength: 30 }), (ops) => {
        stopPlayer();
        reset();
        stopPlayer = startNarrationPlayer();

        const arrived: string[] = [];
        const started: string[] = [];
        const doomed = new Set<string>(); // queued or playing when a cancel hit
        let overlap = false;
        // Zustand re-notifies with the latest state during nested sets, so watch the player's own call instead.
        const realMark = useStore.getState().markSegment;
        useStore.setState({
          markSegment: (id, state) => {
            if (state === "playing") {
              started.push(id);
              // when a segment starts, the previous one must be over
              if (useStore.getState().transcript.some((t) => t.kind === "wysp" && t.state === "playing")) overlap = true;
            }
            realMark(id, state);
          },
        });
        const unsub = () => useStore.setState({ markSegment: realMark });
        let n = 0;
        let turn = 0;
        let cancelledAt = -1; // index into `sent` where the last cancel happened
        for (const op of ops) {
          if (op.kind === "arrive") {
            const id = `s${n}`;
            const msg: CoreMessage = {
              type: "narration.segment",
              segment: {
                id,
                turn_id: `t${turn}`,
                index: n,
                text: "x".repeat(op.chars),
                marker: null,
                cues: op.cue ? [{ at_word: 2, op: "focus", target: "n" }] : [],
              },
            } as CoreMessage;
            arrived.push(id);
            n++;
            useStore.getState().handle(msg);
          } else if (op.kind === "advance") {
            vi.advanceTimersByTime(op.ms);
          } else {
            const st = useStore.getState();
            for (const s of st.queue) doomed.add(s.id);
            if (st.current) doomed.add(st.current.id);
            cancelledAt = sent.length;
            if (op.kind === "cancel")
              st.handle({
                type: "narration.cancel",
                turn_id: `t${turn}`,
                from_index: 0,
              } as CoreMessage);
            else interruptNarration();
            turn++;
          }
          // at most one segment is playing at any time
          expect(
            useStore
              .getState()
              .transcript.filter(
                (t) => t.kind === "wysp" && t.state === "playing",
              ).length,
          ).toBeLessThanOrEqual(1);
        }
        vi.advanceTimersByTime(10 * 60 * 1000); // let everything that survives finish
        unsub();

        expect(overlap).toBe(false);
        // order: starts follow arrival order
        const rank = (id: string) => arrived.indexOf(id);
        expect(started.map(rank)).toEqual(
          [...started.map(rank)].sort((a, b) => a - b),
        );
        expect(new Set(started).size).toBe(started.length);
        // cancellation: nothing doomed starts after its cancel, reports progress as played, or fires a cue afterwards
        // (a doomed segment may have started before the cancel; it must not have started after it)
        const st = useStore.getState();
        for (const id of doomed) {
          const item = st.transcript.find(
            (t) => t.kind === "wysp" && t.segment.id === id,
          );
          expect(item && item.kind === "wysp" && item.state).not.toBe("played");
        }
        for (const m of sent.slice(
          cancelledAt < 0 ? sent.length : cancelledAt,
        )) {
          if (m.type === "narration.progress" || m.type === "narration.cue")
            expect(doomed.has(m.segment_id)).toBe(false);
        }
        // liveness: every segment that was not cancelled was played
        for (const id of arrived) {
          if (doomed.has(id)) continue;
          const item = st.transcript.find(
            (t) => t.kind === "wysp" && t.segment.id === id,
          );
          expect(item && item.kind === "wysp" && item.state).toBe("played");
        }
      }),
      { numRuns: 100 },
    );
  });

  it("plays two queued segments one after the other, in order", () => {
    const seg = (i: number): CoreMessage =>
      ({
        type: "narration.segment",
        segment: {
          id: `s${i}`,
          turn_id: "t",
          index: i,
          text: "hello",
          marker: null,
          cues: [],
        },
      }) as CoreMessage;
    useStore.getState().handle(seg(0));
    useStore.getState().handle(seg(1));
    expect(useStore.getState().current?.id).toBe("s0");
    vi.advanceTimersByTime(1400);
    expect(useStore.getState().current?.id).toBe("s1");
    vi.advanceTimersByTime(1400);
    expect(useStore.getState().current).toBeNull();
    expect(
      sent
        .filter((m) => m.type === "narration.progress")
        .map((m) => (m as { segment_id: string }).segment_id),
    ).toEqual(["s0", "s1"]);
  });
});
