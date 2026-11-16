// The neural voice synthesises about as slowly as real time: the player prefetches at most the NEXT speakable segment,
// one synthesis ahead, and drops prefetched audio on cancel.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CoreMessage, PanelMessage } from "./protocol";
import { startNarrationPlayer, stopSpeech } from "./narration";
import { useStore } from "./store";

const calls: string[] = [];
const resolvers = new Map<string, (b: Blob | null) => void>();
vi.mock("./coreVoice", () => ({
  coreHasNeuralVoice: async () => true,
  coreSpeak: (text: string) => {
    calls.push(text);
    return new Promise<Blob | null>((res) => resolvers.set(text, res));
  },
}));

class FakeAudio {
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  play = () => Promise.resolve();
  pause = () => undefined;
}

let stopPlayer: () => void;
const seg = (i: number, speaker = true): CoreMessage =>
  ({
    type: "narration.segment",
    speaker,
    segment: {
      id: `s${i}`,
      turn_id: "t",
      index: i,
      text: `text${i}`,
      marker: null,
      cues: [],
    },
  }) as CoreMessage;
const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(async () => {
  vi.useFakeTimers();
  calls.length = 0;
  resolvers.clear();
  vi.stubGlobal("Audio", FakeAudio);
  URL.createObjectURL = () => "blob:x";
  URL.revokeObjectURL = () => undefined;
  stopSpeech();
  useStore.setState({
    queue: [],
    current: null,
    transcript: [],
    voiceOn: true,
    send: (_m: PanelMessage) => true,
  });
  stopPlayer = startNarrationPlayer();
  await flush(); // let coreHasNeuralVoice resolve
});
afterEach(() => {
  stopPlayer();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("narration prefetch", () => {
  it("synthesises one segment ahead at most, and only once the current one has its audio", async () => {
    for (let i = 0; i < 4; i++) useStore.getState().handle(seg(i));
    await flush();
    expect(calls).toEqual(["text0"]); // nothing ahead while the current segment waits for its own audio
    resolvers.get("text0")?.(new Blob(["a"]));
    await flush();
    expect(calls).toEqual(["text0", "text1"]); // the next one only, not s2 and s3
  });

  it("skips segments that another Panel speaks and never reaches past the next one", async () => {
    useStore.getState().handle(seg(0));
    useStore.getState().handle(seg(1, false));
    useStore.getState().handle(seg(2));
    useStore.getState().handle(seg(3));
    await flush();
    resolvers.get("text0")?.(new Blob(["a"]));
    await flush();
    expect(calls).toEqual(["text0", "text2"]);
  });

  it("drops prefetched audio on cancel and prefetches nothing for the cancelled turn", async () => {
    for (let i = 0; i < 3; i++) useStore.getState().handle(seg(i));
    await flush();
    resolvers.get("text0")?.(new Blob(["a"]));
    await flush();
    expect(calls).toEqual(["text0", "text1"]);
    useStore
      .getState()
      .handle({
        type: "narration.cancel",
        turn_id: "t",
        from_index: 0,
      } as CoreMessage);
    resolvers.get("text1")?.(new Blob(["b"]));
    await flush();
    vi.advanceTimersByTime(60_000);
    await flush();
    expect(calls).toEqual(["text0", "text1"]); // no synthesis after the cancel
    // a new turn starts clean: its first segment is synthesised, not served from the dropped prefetch
    useStore
      .getState()
      .handle({
        ...seg(5),
        segment: {
          ...(seg(5) as { segment: object }).segment,
          id: "n0",
          text: "again",
        },
      } as CoreMessage);
    await flush();
    expect(calls).toEqual(["text0", "text1", "again"]);
  });

  it("uses the prefetched audio when the next segment starts (no second synthesis)", async () => {
    for (let i = 0; i < 2; i++) useStore.getState().handle(seg(i));
    await flush();
    resolvers.get("text0")?.(new Blob(["a"]));
    await flush();
    resolvers.get("text1")?.(new Blob(["b"]));
    await flush();
    vi.advanceTimersByTime(60_000); // the safety timer ends s0 (the fake audio never ends by itself)
    await flush();
    expect(
      useStore.getState().current?.id === "s1" ||
        useStore.getState().current === null,
    ).toBe(true);
    expect(calls).toEqual(["text0", "text1"]);
  });
});
