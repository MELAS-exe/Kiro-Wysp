// WCAG contrast check of the brand palette pairs used for text. Run: node panel/scripts/contrast.mjs
const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
// Blend a colour with alpha over a background.
const over = (fg, a, bg) => "#" + [1, 3, 5].map((i) => Math.round(parseInt(fg.slice(i, i + 2), 16) * a + parseInt(bg.slice(i, i + 2), 16) * (1 - a)).toString(16).padStart(2, "0")).join("");
export const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};
const P = { night: "#120532", surface: "#1d0e4a", surface2: "#2a1766", line: "#3b2a80", text: "#f4e5fd", muted: "#b9a3e3", wisp: "#ca84fc", accent: "#fe7c9c", ink: "#0d012f", ok: "#22c55e", danger: "#ef4444", brand: "#6503fc" };
const pairs = [
  ["text on night", P.text, P.night],
  ["text on surface", P.text, P.surface],
  ["text on surface2", P.text, P.surface2],
  ["muted on night", P.muted, P.night],
  ["muted on surface", P.muted, P.surface],
  ["muted on surface2", P.muted, P.surface2],
  ["wisp on night", P.wisp, P.night],
  ["wisp on surface", P.wisp, P.surface],
  ["accent on night", P.accent, P.night],
  ["accent on surface2", P.accent, P.surface2],
  ["ink on wisp (primary button)", P.ink, P.wisp],
  ["ink on danger (danger button, irreversible badge; white was 3.76)", P.ink, P.danger],
  ["ink on accent (mic on; white was 2.45)", P.ink, P.accent],
  ["ok on night (steps done)", P.ok, P.night],
  ["ok on surface", P.ok, P.surface],
  ["danger on night (step failed)", P.danger, P.night],
  ["danger on surface", P.danger, P.surface],
  ["danger text #ff8a8a on surface", "#ff8a8a", P.surface],
  ["note error #ffb3c1 on night", "#ffb3c1", P.night],
  ["diff add #86efac on tinted", "#86efac", over("#22c55e", 0.14, P.night)],
  ["diff del #ffb3c1 on tinted", "#ffb3c1", over("#ef4444", 0.14, P.night)],
  ["banner #ffedd5 on #7c2d12", "#ffedd5", "#7c2d12"],
  ["muted on declared tint", P.muted, over(P.muted, 0.1, P.night)],
  ["wisp-ink: lilac illustrative border #8f7bd1 on night (graphic, 3:1)", "#8f7bd1", P.night],
  ["brand on night (never text)", P.brand, P.night],
];
if (process.argv[1]?.endsWith("contrast.mjs")) {
  let bad = 0;
  for (const [n, f, b] of pairs) {
    const r = ratio(f, b);
    const flag = n.includes("never text") || n.includes("graphic") ? "(n/a)" : r >= 4.5 ? "ok" : "FAIL";
    if (flag === "FAIL") bad++;
    console.log(`${r.toFixed(2).padStart(6)}  ${flag.padEnd(5)} ${n}`);
  }
  process.exit(bad ? 1 : 0);
}
