// Voice input: push-to-talk with the browser's speech recognition. Speaking interrupts the narration (barge-in).
import { t } from "./i18n";
import { coreListenStart, coreListenStop, hasCoreListen } from "./coreVoice";
import { interruptNarration } from "./narration";
import { voiceDecision } from "./permissions";
import { useStore } from "./store";

interface RecognitionResultLike {
  isFinal: boolean;
  0: { transcript: string };
}
interface RecognitionEventLike {
  results: ArrayLike<RecognitionResultLike>;
}
interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: RecognitionEventLike) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type RecognitionCtor = new () => RecognitionLike;

const Ctor: RecognitionCtor | undefined =
  (window as unknown as { SpeechRecognition?: RecognitionCtor }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: RecognitionCtor }).webkitSpeechRecognition;

// Listening works with the browser's recognition, or through the Core when the host gave this Panel the pairing token.
export const voiceSupported = hasCoreListen() || Ctor !== undefined;

let rec: RecognitionLike | null = null;
let finalText = "";

/** Route a final transcript: answers a pending permission request by voice when allowed, else it is a message. */
export function handleTranscript(text: string): void {
  const st = useStore.getState();
  const spoken = text.trim();
  if (!spoken) return;
  const perm = st.permission;
  if (perm) {
    const d = voiceDecision(spoken, perm);
    if (d === "approve" || d === "deny") {
      st.send({ type: "permission.respond", request_id: perm.request_id, decision: d, via: "voice" });
      return;
    }
    if (d === "needs_click") {
      note(t("voice.needsClick"));
      return;
    }
  }
  st.addUser(spoken, "voice");
  st.send({ type: "user.message", text: spoken, source: "voice" });
}


function note(text: string): void {
  useStore.setState((s) => ({
    transcript: [...s.transcript, { kind: "note", id: `v${Date.now()}`, text, tone: "error" as const }],
  }));
}

// Core recording: idle -> recording (hold) -> transcribing (release) -> idle.
let coreState: "idle" | "recording" | "transcribing" = "idle";
let coreStart: Promise<string | null> | null = null;

function startCore(): void {
  const st = useStore.getState();
  if (coreState !== "idle") return;
  interruptNarration(); // barge-in
  coreState = "recording";
  st.setListening(true);
  coreStart = coreListenStart();
  void coreStart.then((err) => {
    if (!err) return;
    coreState = "idle";
    useStore.getState().setListening(false);
    note(err);
  });
}

async function stopCore(): Promise<void> {
  if (coreState !== "recording") return;
  coreState = "transcribing";
  useStore.getState().setListening(true, t("voice.transcribing"));
  if (await coreStart) return; // the start failed and was reported
  const r = await coreListenStop();
  coreState = "idle";
  useStore.getState().setListening(false);
  if ("error" in r) note(r.error);
  else handleTranscript(r.text);
}
export function startListening(): void {
  if (hasCoreListen()) return startCore();
  const st = useStore.getState();
  if (!Ctor || st.listening) return;
  interruptNarration(); // barge-in: talking over the tutor stops it
  finalText = "";
  rec = new Ctor();
  rec.lang = st.session?.lang === "fr" ? "fr-FR" : "en-US";
  rec.interimResults = true;
  rec.continuous = false;
  rec.onresult = (e) => {
    let interim = "";
    finalText = "";
    for (let i = 0; i < e.results.length; i++) {
      const r = e.results[i];
      if (!r) continue;
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    useStore.getState().setListening(true, finalText + interim);
  };
  rec.onerror = (e) => {
    useStore.setState((s) => ({
      transcript: [...s.transcript, { kind: "note", id: `v${Date.now()}`, text: t("voice.micError", { error: e.error }), tone: "error" as const }],
    }));
  };
  rec.onend = () => {
    useStore.getState().setListening(false);
    handleTranscript(finalText);
    rec = null;
  };
  try {
    rec.start();
    st.setListening(true);
  } catch {
    st.setListening(false);
  }
}

export function stopListening(): void {
  if (hasCoreListen()) {
    void stopCore();
    return;
  }
  rec?.stop();
}
