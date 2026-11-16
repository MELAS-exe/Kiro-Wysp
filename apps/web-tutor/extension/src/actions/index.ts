/**
 * The closed action catalog. One file per action (id = file name); adding an action means adding a file
 * here and one line below. There is no generic "run" action: nothing in this catalog evaluates code.
 */
import type { ActionSpec } from "@wysp/adapter-sdk";
import { ErrorCode, WyspError } from "@wysp/adapter-sdk";
import type { CsActionOutcome } from "../shared/messages";
import * as clickElement from "./click_element";
import * as fillField from "./fill_field";
import * as focusElement from "./focus_element";
import * as followLink from "./follow_link";
import * as scrollIntoView from "./scroll_into_view";
import * as selectOption from "./select_option";
import * as setChecked from "./set_checked";
import type { ActionContext, ActionModule } from "./types";

const modules: ActionModule[] = [scrollIntoView, focusElement, fillField, selectOption, setChecked, followLink, clickElement];

export const CATALOG: ReadonlyMap<string, ActionModule> = new Map(modules.map((m) => [m.spec.id, m]));

export function actionSpecs(): ActionSpec[] {
  return modules.map((m) => m.spec);
}

export function runAction(
  ctx: ActionContext,
  actionId: string,
  params: Record<string, unknown>,
  dryRun: boolean,
): CsActionOutcome {
  const action = CATALOG.get(actionId);
  if (!action) throw new WyspError(ErrorCode.ACTION_NOT_FOUND, `unknown action: ${actionId}`);
  return action.run(ctx, params, dryRun);
}