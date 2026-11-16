import type { ActionSpec } from "@wysp/adapter-sdk";
import type { Node } from "../cs/locators";
import type { CsActionOutcome } from "../shared/messages";

/** What an action may use. Actions never see chrome.* and never evaluate anything. */
export interface ActionContext {
  doc: Document;
  originKey: string;
  allowlist: readonly string[];
  /** Resolves a ref against the live DOM, or throws TARGET_NOT_FOUND (with candidates). */
  resolve(ref: string): Node;
}

/** One file per action in src/actions; the file name is the action id. */
export interface ActionModule {
  spec: ActionSpec;
  run(ctx: ActionContext, params: Record<string, unknown>, dryRun: boolean): CsActionOutcome;
}