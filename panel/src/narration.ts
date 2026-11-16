// Narration player: plays queued segments one at a time as captions (and speech, when enabled),
// fires their cues, reports progress to the Core, and stops immediately on interruption.
import { coreHasNeuralVoice, coreSpeak } from "./coreVoice";
import { useStore } from "./store";
import type { Segment } from "./protocol";

let timer: ReturnType<typeof setTimeout> | null = null;
let cueTimers: ReturnType<typeof setTimeout>[] = [];
let playing = false;
let playingId = "";
let audio: HTMLAudioElement | null = null;
let audioUrl: string | null = null;

const MS_PER_CHAR = 48;
const MIN_MS = 1400;

function clearTimers(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  cueTimers.forEach(clearTimeout);
  cueTimers = [];
}

function stopAudio(): void {
  if (audio) {
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio = null;
  }
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = null;
}

export function stopSpeech(): void {
  clearTimers();
  playing = false;
  prefetched.clear();
  stopAudio();
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
  prefetched.clear();
  stopAudio();
  const st = useStore.getState();
  st.markSegment(seg.id, "played");
  st.setCurrent(null);
  // Only the Panel that speaks drives the Core's narration timeline; a silent mirror just shows the caption.
  if (seg.speaker !== false) st.send({ type: "narration.progress", segment_id: seg.id, played: true });
  pump();
}

// Neural synthesis takes about as long as the speech lasts: start on queued segments while the current one plays.
let neuralCore = false;
void coreHasNeuralVoice().then((v) => (neuralCore = v));
const prefetched = new Map<string, Promise<Blob | null>>();
function prefetch(lang: string): void {
  if (!neuralCore) return;
  for (const seg of useStore.getState().queue) {
    if (!prefetched.has(seg.id) && seg.speaker !== false) prefetched.set(seg.id, coreSpeak(seg.text, lang));
  }
}

/** The Core's local voice: used when the browser has no speech voices (the IDE's embedded browser). */
function speakViaCore(seg: Segment, lang: string, duration: number): void {
  // Safety net: synthesis plus playback never holds the narration longer than this.
  timer = setTimeout(() => playing && playingId === seg.id && finish(seg), duration * 2.5 + 6000);
  const pending = prefetched.get(seg.id) ?? coreSpeak(seg.text, lang);
  prefetched.delete(seg.id);
  void pending.then((blob) => {
    if (!playing || playingId !== seg.id) return; // interrupted meanwhile
    if (!blob) {
      clearTimers();
      timer = setTimeout(() => finish(seg), duration); // no voice on this machine: the caption stands alone
      return;
    }
    audioUrl = URL.createObjectURL(blob);
    audio = new Audio(audioUrl);
    const done = () => playing && playingId === seg.id && finish(seg);
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
  });
}

function play(seg: Segment): void {
  const st = useStore.getState();
  playing = true;
  playingId = seg.id;
  st.setCurrent(seg);
  st.markSegment(seg.id, "playing");
  const duration = Math.max(MIN_MS, seg.text.length * MS_PER_CHAR);
  const speaker = seg.speaker !== false;
  seg.cues.forEach((cue, i) => {
    if (!speaker) return; // the speaking Panel fires the cues
    const at = Math.min(cue.at_word * 320, duration * 0.7);
    cueTimers.push(setTimeout(() => useStore.getState().send({ type: "narration.cue", segment_id: seg.id, index: i }), at));
  });
  const nativeVoice =
    !neuralCore &&
    typeof speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined" && speechSynthesis.getVoices().length > 0;
  if (!speaker || !st.voiceOn) {
    timer = setTimeout(() => finish(seg), duration); // captions only
  } else if (!nativeVoice) {
    speakViaCore(seg, st.session?.lang ?? "en", duration);
  } else {
    const u = new SpeechSynthesisUtterance(seg.text);
    u.lang = st.session?.lang ?? "en";
    u.rate = 1.02;
    // A cancelled or stale utterance must never finish the segment that is playing now.
    const done = () => playing && playingId === seg.id && finish(seg);
    u.onend = done;
    u.onerror = done;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    // Safety net: some browsers never fire onend when the tab is in the background.
    timer = setTimeout(done, duration * 2.5 + 2000);
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
    if (s.queue.length > prev.queue.length) {
      pump();
      prefetch(useStore.getState().session?.lang ?? "en");
    }
    if (prev.current && !s.current && !playing) return;
    // The store cleared the current segment (cancel): stop audio and timers at once.
    if (prev.current && s.current === null && s.queue.length === 0 && playing) stopSpeech();
  });
  return () => {
    unsubscribe();
    stopSpeech();
  };
}
