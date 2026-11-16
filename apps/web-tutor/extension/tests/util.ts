import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

/** The body of the demo dashboard, without its script (the script is not needed for structure tests). */
export function dashboardBody(): string {
  const html = readFileSync(join(here, "../../demo-dashboard/index.html"), "utf8");
  return (/<body>([\s\S]*)<\/body>/.exec(html)?.[1] ?? "").replace(/<script[\s\S]*?<\/script>/g, "");
}

export function setPage(html: string, url = "http://localhost:5180/"): void {
  (window as unknown as { happyDOM: { setURL(u: string): void } }).happyDOM.setURL(url);
  document.title = "Test page";
  document.body.innerHTML = html;
}

export const KEY = "localhost:5180";

/** Makes an event look like one produced by the user (happy-dom never creates trusted events). */
export function trusted<T extends Event>(ev: T): T {
  Object.defineProperty(ev, "isTrusted", { value: true });
  return ev;
}

export function stable(obs: { observation_id?: string; captured_at?: string }): unknown {
  const { observation_id: _a, captured_at: _b, ...rest } = obs;
  return rest;
}