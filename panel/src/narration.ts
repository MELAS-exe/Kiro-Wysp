// Narration player: plays queued segments one at a time as captions (and speech, when enabled),
// fires their cues, reports progress to the Core, and stops immediately on interruption.
import { useStore } from "./store";
import type { Segment } from "./protocol";

let timer: ReturnType<typeof setTimeout> | null = null;
let cueTimers: ReturnType<typeof setTimeout>[] = [];
let playing = false;

const MS_PER_CHAR = 48;
const MIN_MS = 1400;

function clearTimers(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  cueTimers.forEach(clearTimeout);
  cueTimers = [];
}

export function stopSpeech(): void {
  clearTimers();
  playing = false;
  if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
}

/** Interrupt right now: stop audio and captions locally, then tell the Core. */
export function interruptNarration(): void {
  stopSpeech();
  const st = useStore.getState();
  st.cancelNarration();
  st.send({ type: "user.interrupt" });
}

function finish(seg: Segment): void {
  clearTimers();
  playing = false;
  const st = useStore.getState();
  st.markSegment(seg.id, "played");
  st.setCurrent(null);
  st.send({ type: "narration.progress", segment_id: seg.id, played: true });
  pump();
}

function play(seg: Segment): void {
  const st = useStore.getState();
  playing = true;
  st.setCurrent(seg);
  st.markSegment(seg.id, "playing");
  const duration = Math.max(MIN_MS, seg.text.length * MS_PER_CHAR);
  seg.cues.forEach((cue, i) => {
    const at = Math.min(cue.at_word * 320, duration * 0.7);
    cueTimers.push(setTimeout(() => useStore.getState().send({ type: "narration.cue", segment_id: seg.id, index: i }), at));
  });
  const canSpeak = st.voiceOn && typeof speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
  if (canSpeak) {
    const u = new SpeechSynthesisUtterance(seg.text);
    u.lang = st.session?.lang ?? "en";
    u.rate = 1.02;
    u.onend = () => playing && finish(seg);
    u.onerror = () => playing && finish(seg);
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    // Safety net: some browsers never fire onend when the tab is in the background.
    timer = setTimeout(() => playing && finish(seg), duration * 2.5 + 2000);
  } else {
    timer = setTimeout(() => finish(seg), duration);
  }
}

function pump(): void {
  if (playing) return;
  const next = useStore.getState().popQueue();
  if (next) play(next);
}

/** Start the player: it reacts to new segments and to cancellations. Returns a stop function. */
export function startNarrationPlayer(): () => void {
  const unsubscribe = useStore.subscribe((s, prev) => {
    if (s.queue.length > prev.queue.length) pump();
    if (prev.current && !s.current && !playing) return;
    // The store cleared the current segment (cancel): stop audio and timers at once.
    if (prev.current && s.current === null && s.queue.length === 0 && playing) stopSpeech();
  });
  return () => {
    unsubscribe();
    stopSpeech();
  };
}
