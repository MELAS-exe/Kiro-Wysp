import { ErrorCode, WyspError } from "@wysp/adapter-sdk";
import type { UndoRecord } from "../shared/messages";
import type { ActionContext } from "./types";
import { readChecked, setNativeValue } from "./helpers";

/** Restores the state saved by a reversible action. Not an action: only reachable through adapter.undo. */
export function applyUndo(ctx: ActionContext, record: UndoRecord): string[] {
  let node;
  try {
    node = ctx.resolve(record.ref);
  } catch {
    throw new WyspError(ErrorCode.UNDO_UNAVAILABLE, "the element is gone, nothing to undo");
  }
  if (record.kind === "value") {
    setNativeValue(node.el as HTMLInputElement, record.previous);
  } else if (readChecked(node.el) !== record.previous) {
    (node.el as HTMLElement).click();
  }
  return [record.ref];
}