import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PageAgent } from "../src/cs/agent";
import { guardedObservation, buildContext, buildObservation } from "../src/cs/snapshot";
import { isSensitiveField, truncate } from "../src/cs/redact";
import { originAllowed, normalizeOrigin } from "../src/shared/config";
import type { CsToSw } from "../src/shared/messages";
import { KEY, setPage, trusted } from "./util";

const secretArb = fc
  .stringMatching(/^[a-z0-9]{6,16}$/)
  .map((s) => `S3CR3T${s}`);

const sensitiveHtml = (s: string[]): string => `
  <main>
    <form aria-label="Payment">
      <label for="pw">Password</label><input id="pw" type="password" value="${s[0]}">
      <label for="cc">Card number</label><input id="cc" type="text" autocomplete="cc-number" value="${s[1]}">
      <label for="otp">Code</label><input id="otp" type="text" autocomplete="one-time-code" value="${s[2]}">
      <input type="hidden" name="csrf" value="${s[3]}">
      <div data-wysp-sensitive><label for="x">Private note</label><textarea id="x">${s[4]}</textarea></div>
      <label for="name">Name</label><input id="name" type="text" value="Ada">
    </form>
  </main>`;

describe("prop: WEB-P1 redaction", () => {
  afterEach(() => vi.useRealTimers());

  it("no sensitive value appears in the observation, the context or any event", () => {
    fc.assert(
      fc.property(fc.array(secretArb, { minLength: 5, maxLength: 5 }), (secrets) => {
        setPage(sensitiveHtml(secrets));
        const sent: CsToSw[] = [];
        const agent = new PageAgent(document, () => ["http://localhost:5180"], (m) => sent.push(m));
        const obs = buildObservation({ doc: document, originKey: KEY, stateVersion: 1 });
        const out = JSON.stringify([obs, buildContext(document, KEY, true, obs)]);
        for (const s of secrets) expect(out).not.toContain(s);
        expect(out).toContain("[redacted]");
        expect(out).toContain("Ada"); // ordinary fields keep their value
        // User-action events carry no sensitive values either.
        agent.tracker.start();
        for (const id of ["pw", "cc", "otp", "x", "name"]) {
          const el = document.getElementById(id)!;
          el.dispatchEvent(trusted(new Event("change", { bubbles: true })));
        }
        agent.stop();
        const events = JSON.stringify(sent);
        for (const s of secrets) expect(events).not.toContain(s);
        expect(sent.length).toBeGreaterThan(0);
      }),
      { numRuns: 25 },
    );
  });

  it("classifies sensitive fields", () => {
    setPage(sensitiveHtml(["a", "b", "c", "d", "e"]));
    for (const id of ["pw", "cc", "otp", "x"]) expect(isSensitiveField(document.getElementById(id)!)).toBe(true);
    expect(isSensitiveField(document.getElementById("name")!)).toBe(false);
    expect(isSensitiveField(document.querySelector("input[type=hidden]")!)).toBe(true);
  });

  it("truncates long text to 200 characters", () => {
    fc.assert(fc.property(fc.string({ minLength: 0, maxLength: 1000 }), (s) => truncate(s).length <= 200));
  });
});

describe("prop: WEB-P6 allowlist enforcement", () => {
  const ALLOW = ["http://localhost:5180"];
  const hostArb = fc.domain().filter((d) => d !== "localhost");
  const originArb = fc.tuple(fc.constantFrom("http", "https"), hostArb, fc.option(fc.integer({ min: 1, max: 65535 }), { nil: undefined })).map(
    ([scheme, host, port]) => `${scheme}://${host}${port ? `:${port}` : ""}`,
  );

  beforeEach(() => setPage("<main></main>"));

  it("originAllowed accepts exactly the allowlisted origins", () => {
    fc.assert(
      fc.property(originArb, (origin) => {
        const norm = normalizeOrigin(origin);
        expect(originAllowed(origin, ALLOW)).toBe(norm === "http://localhost:5180");
      }),
    );
    expect(originAllowed("http://localhost:5180/some/path?q=1", ALLOW)).toBe(true);
    expect(originAllowed("http://localhost:5181", ALLOW)).toBe(false);
    expect(originAllowed("https://localhost:5180", ALLOW)).toBe(false);
    expect(originAllowed("http://sub.localhost:5180", ALLOW)).toBe(false);
    expect(originAllowed("chrome://settings", ALLOW)).toBe(false);
    expect(originAllowed(undefined, ALLOW)).toBe(false);
  });

  it("nothing leaves a page that is not allowlisted (observation, context, actions, events)", () => {
    fc.assert(
      fc.property(originArb, (origin) => {
        setPage(sensitiveHtml(["a1b2c3d4", "x", "y", "z", "w"]) + `<button>Pay</button>`, `${origin}/`);
        const sent: CsToSw[] = [];
        const agent = new PageAgent(document, () => ALLOW, (m) => sent.push(m));
        agent.start();
        const obs = guardedObservation({ doc: document, originKey: new URL(origin).host, stateVersion: 3, allowlist: ALLOW });
        expect(obs.entities).toEqual([]);
        expect(obs.counts).toEqual({ not_allowed: 1 });
        const reply = agent.handle({ wysp: "observe" });
        expect(reply.ok && (reply.result as { entities: unknown[] }).entities).toEqual([]);
        const ctx = agent.handle({ wysp: "context" });
        expect(JSON.stringify(ctx)).toContain("not_allowed");
        expect(agent.handle({ wysp: "execute", actionId: "click_element", params: { target: `web://x/button~pay` }, dryRun: false }).ok).toBe(false);
        document.querySelector("button")!.dispatchEvent(trusted(new Event("click", { bubbles: true })));
        agent.tracker.flush();
        agent.stop();
        expect(sent).toEqual([]);
      }),
      { numRuns: 20 },
    );
  });
});