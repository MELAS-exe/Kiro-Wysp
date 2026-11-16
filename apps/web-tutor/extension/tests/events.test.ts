import fc from "fast-check";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PageAgent } from "../src/cs/agent";
import { Overlay } from "../src/cs/overlay";
import type { CsToSw } from "../src/shared/messages";
import { setPage, trusted } from "./util";

const PAGE = `<main><section aria-label="Form"><label for="n">Name</label><input id="n" type="text" value="a"><button>Go</button></section></main>`;
const NAME = "web://localhost:5180/region~form/textbox~name";

function setup() {
  setPage(PAGE);
  const sent: CsToSw[] = [];
  const agent = new PageAgent(document, () => ["http://localhost:5180"], (m) => sent.push(m));
  agent.start();
  return { agent, sent };
}
const userActions = (sent: CsToSw[]) => sent.filter((m) => m.wyspEvent === "user_action") as Extract<CsToSw, { wyspEvent: "user_action" }>[];

describe("events and origin tagging", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("tags trusted events as user and synthetic ones as wysp", () => {
    const { agent, sent } = setup();
    const btn = document.querySelector("button")!;
    btn.dispatchEvent(trusted(new MouseEvent("click", { bubbles: true })));
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(userActions(sent).map((a) => [a.kind, a.origin])).toEqual([["click", "user"], ["click", "wysp"]]);
    expect(userActions(sent)[0]?.target).toBe("web://localhost:5180/region~form/button~go");
    agent.stop();
  });

  it("tags state changes caused by a Wysp action as wysp and later ones as user", () => {
    const { agent, sent } = setup();
    const reply = agent.handle({ wysp: "execute", actionId: "fill_field", params: { target: NAME, value: "b" }, dryRun: false });
    expect(reply.ok).toBe(true);
    vi.advanceTimersByTime(400);
    const states = () => sent.filter((m) => m.wyspEvent === "state_changed") as Extract<CsToSw, { wyspEvent: "state_changed" }>[];
    expect(states().at(-1)).toMatchObject({ origin: "wysp", changed: [NAME] });
    (document.getElementById("n") as HTMLInputElement).value = "typed by the user";
    agent.tracker.flush();
    expect(states().at(-1)).toMatchObject({ origin: "user", changed: [NAME] });
    agent.stop();
  });

  it("prop: WEB-P5 (unit level) any interleaving of Wysp actions and user events is tagged correctly", () => {
    fc.assert(
      fc.property(fc.array(fc.constantFrom("user", "wysp"), { minLength: 1, maxLength: 12 }), (ops) => {
        const { agent, sent } = setup();
        const expected: string[] = [];
        ops.forEach((op, i) => {
          if (op === "wysp") {
            agent.handle({ wysp: "execute", actionId: "fill_field", params: { target: NAME, value: `w${i}` }, dryRun: false });
          } else {
            const el = document.getElementById("n") as HTMLInputElement;
            el.dispatchEvent(trusted(new Event("change", { bubbles: true })));
          }
          agent.tracker.flush(); // consumes the execution window
        });
        for (const a of userActions(sent)) expected.push(a.origin);
        const states = sent.filter((m) => m.wyspEvent === "state_changed") as Extract<CsToSw, { wyspEvent: "state_changed" }>[];
        // Every state change in this run was caused by a Wysp action: none may be tagged user.
        for (const s of states) expect(s.origin).toBe("wysp");
        // Every trusted change event is a user action.
        expect(expected.filter((o) => o === "user").length).toBe(ops.filter((o) => o === "user").length);
        agent.stop();
      }),
      { numRuns: 25 },
    );
  });

  it("sends focus changes as selection_changed", () => {
    const { agent, sent } = setup();
    (document.getElementById("n") as HTMLInputElement).focus();
    agent.tracker.flush();
    expect(sent).toContainEqual({ wyspEvent: "selection_changed", focus: [NAME] });
    agent.stop();
  });
});

describe("overlay highlight", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setPage(PAGE);
  });
  afterEach(() => vi.useRealTimers());

  it("timed highlights clear themselves, persistent ones stay until cleared", () => {
    const dismissed: string[] = [];
    const o = new Overlay(document, (r) => dismissed.push(r));
    const el = document.querySelector("button")!;
    o.show({ ref: "r1", getEl: () => el, durationMs: 1000 }, "pulse");
    expect(document.querySelector("[data-wysp-overlay]")).not.toBeNull();
    vi.advanceTimersByTime(1100);
    expect(document.querySelector("[data-wysp-overlay]")).toBeNull();
    o.show({ ref: "r2", getEl: () => el, durationMs: 0 }, "outline");
    vi.advanceTimersByTime(60_000);
    expect(o.current?.ref).toBe("r2");
    expect(o.clear()).toBe(true);
    expect(o.clear()).toBe(false);
  });

  it("uses a closed shadow root and does not intercept pointer events", () => {
    const o = new Overlay(document, () => undefined);
    o.show({ ref: "r", getEl: () => document.querySelector("button"), durationMs: 0 }, "pulse");
    const host = document.querySelector("[data-wysp-overlay]") as HTMLElement;
    expect(host.shadowRoot).toBeNull(); // closed
    expect(host.style.pointerEvents).toBe("none");
    o.clear();
  });

  it("a persistent highlight is dismissed by a user interaction with its element, not by Wysp's own events", () => {
    const dismissed: string[] = [];
    const o = new Overlay(document, (r) => dismissed.push(r));
    const el = document.querySelector("button")!;
    o.show({ ref: "r", getEl: () => el, durationMs: 0 }, "pulse");
    el.dispatchEvent(new MouseEvent("click", { bubbles: true })); // synthetic: Wysp
    expect(dismissed).toEqual([]);
    document.body.dispatchEvent(trusted(new MouseEvent("click", { bubbles: true }))); // elsewhere
    expect(dismissed).toEqual([]);
    el.dispatchEvent(trusted(new MouseEvent("click", { bubbles: true })));
    expect(dismissed).toEqual(["r"]);
    expect(o.current).toBeNull();
  });

  it("agent: highlight, then highlight_dismissed on user click, and clear_highlight reports cleared", () => {
    const { agent, sent } = setup();
    const ref = "web://localhost:5180/region~form/button~go";
    expect(agent.handle({ wysp: "highlight", ref, style: "pulse", durationMs: 0 }).ok).toBe(true);
    document.querySelector("button")!.dispatchEvent(trusted(new MouseEvent("click", { bubbles: true })));
    expect(sent).toContainEqual({ wyspEvent: "highlight_dismissed", ref });
    expect(agent.handle({ wysp: "clear_highlight" })).toEqual({ ok: true, result: { cleared: false } });
    agent.handle({ wysp: "highlight", ref, style: "outline", durationMs: 0 });
    expect(agent.handle({ wysp: "clear_highlight" })).toEqual({ ok: true, result: { cleared: true } });
    const bad = agent.handle({ wysp: "highlight", ref: "web://localhost:5180/button~nope", style: "pulse", durationMs: 0 });
    expect(bad).toMatchObject({ ok: false, code: -32012 });
    agent.stop();
  });
});