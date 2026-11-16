/** Messages between the service worker (SW) and the content script (CS). */
import type { ActionResult, Context, Observation } from "@wysp/adapter-sdk";

export type UndoRecord =
  | { kind: "value"; ref: string; previous: string }
  | { kind: "checked"; ref: string; previous: boolean };

/** What the CS returns for an action. The SW adds state_version and swaps `undo` for an undo token. */
export interface CsActionOutcome {
  status: "ok" | "failed";
  changed: string[];
  message?: string;
  preview?: unknown;
  undo?: UndoRecord;
}

export type SwToCs =
  | {
      wysp: "observe";
      scope?: { level?: string; root?: string | null; depth?: number | null };
    }
  | { wysp: "context" }
  | {
      wysp: "execute";
      actionId: string;
      params: Record<string, unknown>;
      dryRun: boolean;
    }
  | { wysp: "undo"; record: UndoRecord }
  | {
      wysp: "highlight";
      ref: string;
      style: "pulse" | "outline";
      durationMs: number;
      label?: string;
    }
  | { wysp: "clear_highlight" };

export type CsReply =
  | {
      ok: true;
      result:
        | Observation
        | Context
        | CsActionOutcome
        | { cleared: boolean }
        | { ok: true };
    }
  | { ok: false; code: number; message: string; data?: unknown };

/** CS to SW notifications, forwarded to the Core as event.* notifications. */
export type CsToSw =
  | {
      wyspEvent: "state_changed";
      changed: string[];
      origin: "user" | "wysp" | "unknown";
    }
  | { wyspEvent: "selection_changed"; focus: string[] }
  | {
      wyspEvent: "user_action";
      kind: string;
      target: string | null;
      details: Record<string, unknown>;
      origin: "user" | "wysp" | "unknown";
    }
  | { wyspEvent: "highlight_dismissed"; ref: string };

export type { ActionResult };
