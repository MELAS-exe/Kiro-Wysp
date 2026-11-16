// @vitest-environment jsdom
// Component tests: exercise card (task 8), evidence labels, accessibility (task 9, axe-core on the main components).
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emptyBoard } from "../board/applyOps";
import { nodeAriaLabel } from "../board/BoardView";
import type {
  BoardNode,
  ExerciseState,
  PanelMessage,
  PermissionRequest,
} from "../protocol";
import { useStore } from "../store";
import { Chat } from "./Chat";
import { Corner } from "./Corner";
import { ExerciseCard } from "./ExerciseCard";
import { ExploreCard } from "./ExploreCard";
import { PermissionDialog } from "./PermissionDialog";

const sent: PanelMessage[] = [];
const EX: ExerciseState = {
  exercise_id: "e1",
  prompt: "Add a Subdivision modifier",
  skills: [],
  status: "active",
  attempts: 1,
  max_attempts: 3,
  hints_used: 0,
  hints_total: 2,
};
const PERM: PermissionRequest = {
  type: "permission.request",
  request_id: "r1",
  action_id: "add_modifier",
  title: "Add a modifier",
  target: "Pumpkin",
  risk: "reversible",
  reversible: true,
  rationale: "To show the effect.",
  preview: { diff: "+ a\n- b", file: "x.py", lines: "1-2" },
  voice_allowed: true,
  can_grant: true,
  timeout_s: 30,
};

beforeEach(() => {
  Element.prototype.scrollIntoView = () => {}; // not implemented by jsdom
  sent.length = 0;
  useStore.setState({
    send: (m: PanelMessage) => (sent.push(m), true),
    transcript: [],
    lesson: {
      lesson_id: "l1",
      title: "Modifiers",
      status: "running",
      step: 2,
      total: 5,
    },
    exercise: EX,
    permission: null,
    clarification: null,
    explore: null,
    status: "idle",
    connected: true,
    board: emptyBoard(),
    mode: "side",
    view: "chat",
  });
});
afterEach(cleanup);

async function violations(container: HTMLElement) {
  // color-contrast needs real layout and styles; contrast is measured by panel/scripts/contrast.mjs instead.
  const r = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  return r.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`,
  );
}

describe("ExerciseCard (task 8)", () => {
  it("shows the lesson step, attempts and hints", () => {
    render(<ExerciseCard />);
    expect(screen.getByText("Step 2 of 5")).toBeTruthy();
    expect(screen.getByText("Add a Subdivision modifier")).toBeTruthy();
    expect(screen.getByText(/Attempts 1\/3 · hints 0\/2/)).toBeTruthy();
  });

  it("Hint and I'm done send exactly the user message a person could type", () => {
    render(<ExerciseCard />);
    fireEvent.click(screen.getByRole("button", { name: "Hint" }));
    fireEvent.click(screen.getByRole("button", { name: "I'm done" }));
    expect(sent).toEqual([
      { type: "user.message", text: "Give me a hint.", source: "typed" },
      {
        type: "user.message",
        text: "I think I am done, please check.",
        source: "typed",
      },
    ]);
  });

  it("disables Hint when all hints are used", () => {
    useStore.setState({ exercise: { ...EX, hints_used: 2 } });
    render(<ExerciseCard />);
    expect(
      (screen.getByRole("button", { name: "Hint" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it.each([
    ["passed", /verified in the application/i],
    ["declared", /declared by you, not checked/i],
    ["failed", /not verified/i],
  ] as const)("labels a finished exercise: %s", (status, label) => {
    useStore.setState({ exercise: { ...EX, status } });
    render(<ExerciseCard />);
    expect(screen.getByRole("status").textContent).toMatch(label);
    expect(screen.queryByRole("button", { name: "Hint" })).toBeNull();
  });
});

describe("Chat evidence labels (task 8)", () => {
  const ev = (etype: string, ok: boolean) => ({
    kind: "evidence" as const,
    id: "e",
    title: "Subdivision added",
    scope: "x",
    ok,
    etype,
  });
  it("verified evidence says Verified in the application", () => {
    useStore.setState({ transcript: [ev("verified", true)] });
    render(<Chat />);
    expect(
      screen.getByText(/Verified in the application: Subdivision added/),
    ).toBeTruthy();
  });
  it("declared evidence is not presented as verified", () => {
    useStore.setState({ transcript: [ev("declared", true)] });
    render(<Chat />);
    expect(
      screen.getByText(/Declared by you, not checked in the application/),
    ).toBeTruthy();
    expect(screen.queryByText(/Verified in the application/)).toBeNull();
  });
  it("failed verification says so", () => {
    useStore.setState({ transcript: [ev("verified", false)] });
    render(<Chat />);
    expect(screen.getByText(/Could not be verified/)).toBeTruthy();
  });
});

describe("Accessibility (task 9)", () => {
  it("Chat with messages, clarification, cards has no axe violation", async () => {
    useStore.setState({
      transcript: [
        { kind: "user", id: "u1", text: "What is this?", source: "typed" },
        {
          kind: "wysp",
          id: "w1",
          segment: {
            id: "s",
            index: 0,
            text: "A pumpkin.",
            marker: "likely",
          } as never,
          state: "played",
        },
        {
          kind: "evidence",
          id: "e1",
          title: "ok",
          scope: "x",
          ok: true,
          etype: "verified",
        },
      ],
      clarification: { question: "Which one?", options: ["A", "B"] },
      explore: {
        phase: "offer",
        files: 0,
        symbols: 0,
        read: 0,
        briefs: 0,
        note: "",
      } as never,
      status: "thinking",
      activity: "Looking",
    });
    const { container } = render(<Chat />);
    expect(await violations(container)).toEqual([]);
    expect(screen.getByRole("log").getAttribute("aria-live")).toBe("polite");
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
  });

  it("ExploreCard in each phase has no axe violation", async () => {
    for (const phase of ["offer", "mapping", "ready", "failed"]) {
      useStore.setState({
        explore: {
          phase,
          files: 3,
          symbols: 9,
          read: 1,
          briefs: 1,
          note: "",
        } as never,
      });
      const { container, unmount } = render(<ExploreCard />);
      expect(await violations(container)).toEqual([]);
      unmount();
    }
  });

  it("ExerciseCard has no axe violation", async () => {
    const { container } = render(<ExerciseCard />);
    expect(await violations(container)).toEqual([]);
  });

  it("PermissionDialog has no axe violation, focuses Deny, traps Tab and denies on Esc", async () => {
    useStore.setState({ permission: PERM });
    const { container } = render(<PermissionDialog />);
    expect(await violations(container)).toEqual([]);
    const dlg = screen.getByRole("alertdialog");
    expect(dlg.getAttribute("aria-modal")).toBe("true");
    const deny = screen.getByRole("button", { name: "Deny" });
    expect(document.activeElement).toBe(deny);
    // Tab from the last button wraps to the first; Shift+Tab from the first wraps to the last.
    const buttons = screen.getAllByRole("button");
    buttons[buttons.length - 1]!.focus();
    fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(dlg.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(buttons[buttons.length - 1]);
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(sent).toContainEqual({
      type: "permission.respond",
      request_id: "r1",
      decision: "deny",
      via: "click",
    });
    expect(useStore.getState().permission).toBeNull();
  });

  it("Corner: tabs semantics, menu is a labelled disclosure, no axe violation", async () => {
    const node: BoardNode = {
      id: "n",
      ref: null,
      kind: "object",
      label: "Pumpkin",
      provenance: "observed",
      confidence: 1,
      props_view: [],
      group: null,
      badges: [],
      order: 0,
    };
    useStore.setState({
      board: { ...emptyBoard(), nodes: [node] },
      adapters: [],
      session: null,
    });
    const { container } = render(<Corner />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Chat", "Diagram"]);
    expect(tabs[0]!.getAttribute("aria-selected")).toBe("true");
    fireEvent.click(tabs[1]!);
    expect(useStore.getState().view).toBe("board");
    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    expect(
      screen
        .getByRole("button", { name: "Menu" })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    expect(screen.getByRole("group", { name: "Wysp settings" })).toBeTruthy();
    expect(await violations(container)).toEqual([]);
    fireEvent.change(screen.getByRole("combobox", { name: "Layout mode" }), {
      target: { value: "compact" },
    });
    expect(useStore.getState().mode).toBe("compact");
    expect(document.documentElement.dataset.mode).toBe("compact");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(
      screen
        .getByRole("button", { name: "Menu" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Menu" }),
    );
  });

  it("Board nodes carry a text alternative of their provenance", () => {
    const n: BoardNode = {
      id: "n",
      ref: "blender://o",
      kind: "object",
      label: "Pumpkin",
      provenance: "inferred",
      confidence: 0.7,
      props_view: [],
      group: null,
      badges: [],
      order: null,
    };
    expect(nodeAriaLabel(n)).toBe(
      "object Pumpkin, likely, inferred, confidence 70 percent",
    );
    expect(
      nodeAriaLabel({ ...n, provenance: "observed", confidence: 1 }),
    ).toContain("observed in the application");
    expect(
      nodeAriaLabel({ ...n, provenance: "illustrative", confidence: 1 }),
    ).toContain("example");
  });

  it("compact mode keeps only the last exchange in the chat", () => {
    const items = [1, 2, 3].map((i) => ({
      kind: "user" as const,
      id: `u${i}`,
      text: `m${i}`,
      source: "typed",
    }));
    useStore.setState({
      transcript: items,
      mode: "compact",
      lesson: null,
      exercise: null,
    });
    render(<Chat />);
    expect(screen.queryByText("m1")).toBeNull();
    expect(screen.getByText("m3")).toBeTruthy();
    vi.restoreAllMocks();
  });
});
