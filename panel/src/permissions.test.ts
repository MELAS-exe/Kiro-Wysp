import fc from "fast-check";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { canApproveByVoice, voiceDecision } from "./permissions";
import type { PanelMessage, PermissionRequest } from "./protocol";
import { useStore } from "./store";

vi.mock("./coreVoice", () => ({
  coreHasNeuralVoice: async () => false,
  coreSpeak: async () => null,
  hasCoreListen: () => false,
  coreListenStart: async () => null,
  coreListenStop: async () => ({ text: "" }),
}));

const YES_WORDS = [
  "yes",
  "Yes",
  "yeah",
  "yep",
  "ok",
  "okay",
  "approve",
  "go ahead",
  "do it",
  "sure",
  "confirm",
];
const yesArb = fc
  .tuple(
    fc.constantFrom(...YES_WORDS),
    fc.constantFrom("", " please", ", thanks", "!"),
  )
  .map(([a, b]) => a + b);
const riskArb = fc.oneof(
  fc.constantFrom("read_only", "ui_state", "reversible", "irreversible"),
  fc.string({ maxLength: 12 }),
);

const request = (risk: string, voice_allowed: boolean): PermissionRequest =>
  ({
    type: "permission.request",
    request_id: "r1",
    action_id: "a",
    title: "t",
    target: "x",
    risk,
    reversible: risk !== "irreversible",
    rationale: "",
    preview: null,
    voice_allowed,
    can_grant: false,
    timeout_s: 60,
  }) as unknown as PermissionRequest;

describe("voice approval", () => {
  it("prop: a spoken yes never approves an irreversible action (PAN-P5)", () => {
    fc.assert(
      fc.property(yesArb, fc.boolean(), (said, voiceAllowed) => {
        expect(canApproveByVoice("irreversible")).toBe(false);
        expect(
          voiceDecision(said, {
            risk: "irreversible",
            voice_allowed: voiceAllowed,
          }),
        ).toBe("needs_click");
      }),
      { numRuns: 100 },
    );
  });

  it("prop: a spoken yes approves only when the risk allows it and the Core allows voice (PAN-P5)", () => {
    fc.assert(
      fc.property(yesArb, riskArb, fc.boolean(), (said, risk, voiceAllowed) => {
        const d = voiceDecision(said, { risk, voice_allowed: voiceAllowed });
        expect(d === "approve").toBe(risk !== "irreversible" && voiceAllowed);
      }),
      { numRuns: 100 },
    );
  });

  it("a spoken no is always accepted, and other words are ordinary messages", () => {
    expect(
      voiceDecision("no", { risk: "irreversible", voice_allowed: false }),
    ).toBe("deny");
    expect(
      voiceDecision("rotate the cube", {
        risk: "reversible",
        voice_allowed: true,
      }),
    ).toBeNull();
  });
});

describe("handleTranscript wiring", () => {
  let handleTranscript: (t: string) => void;
  beforeAll(async () => {
    vi.stubGlobal("window", {});
    ({ handleTranscript } = await import("./voice"));
  });

  it("prop: no permission.respond approve via voice is ever sent for an irreversible request (PAN-P5)", () => {
    fc.assert(
      fc.property(yesArb, fc.boolean(), (said, voiceAllowed) => {
        const sent: PanelMessage[] = [];
        useStore.setState({
          permission: request("irreversible", voiceAllowed),
          send: (m: PanelMessage) => (sent.push(m), true),
        });
        handleTranscript(said);
        expect(sent.filter((m) => m.type === "permission.respond")).toEqual([]);
      }),
      { numRuns: 100 },
    );
  });

  it("sends a voice approval for a reversible request", () => {
    const sent: PanelMessage[] = [];
    useStore.setState({
      permission: request("reversible", true),
      send: (m: PanelMessage) => (sent.push(m), true),
    });
    handleTranscript("yes");
    expect(sent).toEqual([
      {
        type: "permission.respond",
        request_id: "r1",
        decision: "approve",
        via: "voice",
      },
    ]);
  });
});
