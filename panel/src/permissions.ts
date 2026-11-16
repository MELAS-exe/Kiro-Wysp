// Pure rules for answering a permission request by voice. The Core enforces the same rule; the Panel never
// even sends a spoken approval for an irreversible action (trust-and-safety: never approved by voice).

// Both regexes run on normalized text (lower-case, no accents, ASCII apostrophe).
const YES =
  /^(yes|yeah|yep|ok|okay|approve|approved|go ahead|do it|sure|confirm|oui|ouais|d'?accord|approuve|approuves|approuvee|approuver|vas-y|allez-y|bien sur|confirme|confirmer)\b/;
const NO =
  /^(no|nope|deny|cancel|stop|don't|do not|refuse|refuses|refuser|non|nan|annule|annuler|arrete|pas question|ne fais pas)\b/;

/** Lower-case, strip accents and unify apostrophes, so "D’accord", "approuvé" and "Arrête" match. */
function normalize(text: string): string {
  return text
    .trim()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[\u2018\u2019\u02bc`]/g, "'")
    .toLowerCase();
}

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
  const t = normalize(text);
  if (YES.test(t))
    return canApproveByVoice(perm.risk) && perm.voice_allowed !== false
      ? "approve"
      : "needs_click";
  if (NO.test(t)) return "deny"; // refusing is always safe
  return null;
}
