// Pure rules for answering a permission request by voice. The Core enforces the same rule; the Panel never
// even sends a spoken approval for an irreversible action (trust-and-safety: never approved by voice).

const YES =
  /^(yes|yeah|yep|ok|okay|approve|approved|go ahead|do it|sure|confirm)\b/i;
const NO = /^(no|nope|deny|cancel|stop|don't|do not|refuse)\b/i;

/** Irreversible actions need an explicit click with a preview. */
export function canApproveByVoice(risk: string): boolean {
  return risk !== "irreversible";
}

export type VoiceDecision = "approve" | "deny" | "needs_click";

/**
 * What a transcript means for a pending permission request: a decision to send with `via: "voice"`,
 * "needs_click" for a spoken yes that is not allowed for this request, or null for an ordinary message.
 */
export function voiceDecision(
  text: string,
  perm: { risk: string; voice_allowed?: boolean },
): VoiceDecision | null {
  const t = text.trim();
  if (YES.test(t))
    return canApproveByVoice(perm.risk) && perm.voice_allowed !== false
      ? "approve"
      : "needs_click";
  if (NO.test(t)) return "deny"; // refusing is always safe
  return null;
}
