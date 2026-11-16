/**
 * `defineAction()`: declare an adapter action once (its catalog entry and its code) and let the SDK validate the
 * parameters with ajv before the code runs, so that an invalid call is refused with -32602 and changes nothing.
 *
 * Imported from `@wysp/adapter-sdk/actions`, not from the package root: ajv compiles validators with `new Function`,
 * which Manifest V3 extension pages and service workers forbid (no `unsafe-eval`). Hosts with that restriction
 * validate by hand (see the web tutor's `helpers.ts`) and import only the root.
 */
import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv/dist/2020";
import type { ActionResult, ActionSpec } from "./generated";
import { ErrorCode, WyspError } from "./errors";

export type ActionParams = Record<string, unknown>;

/** What a handler returns: the contract's ActionResult without `state_version`, which the registry fills in. */
export type ActionOutcome = Omit<ActionResult, "state_version" | "status"> & {
  status?: ActionResult["status"];
};

/** What a registry needs from an action, whatever its parameter type. */
export type RegisteredAction = Pick<ActionDefinition, "spec" | "run">;

export interface ActionDefinition<P extends ActionParams = ActionParams> {
  spec: ActionSpec;
  /** Validate `params` against `spec.params_schema`; throws WyspError(-32602) with the ajv errors in `data`. */
  validate(params: unknown): P;
  /** Validate, then run. `dryRun` is true for previews: the handler must not change anything then. */
  run(params: unknown, dryRun?: boolean): Promise<ActionOutcome>;
}

export interface ActionInit<P extends ActionParams> {
  id: string;
  title: ActionSpec["title"];
  description: string;
  params_schema: Record<string, unknown>;
  risk: ActionSpec["risk"];
  /** Defaults to `risk === "reversible"`. */
  reversible?: boolean;
  preconditions?: ActionSpec["preconditions"];
  postconditions?: ActionSpec["postconditions"];
  guide?: ActionSpec["guide"];
  handler(
    params: P,
    dryRun: boolean,
  ): Promise<ActionOutcome | void> | ActionOutcome | void;
}

const ajv = new Ajv2020({ allErrors: true, strict: false });

export function defineAction<P extends ActionParams = ActionParams>(
  init: ActionInit<P>,
): ActionDefinition<P> {
  const reversible = init.reversible ?? init.risk === "reversible";
  if (init.risk === "reversible" && !reversible)
    throw new Error(`${init.id}: risk 'reversible' requires reversible=true`);
  if (init.risk === "irreversible" && reversible)
    throw new Error(
      `${init.id}: risk 'irreversible' requires reversible=false`,
    );
  if (/(^|_)(eval|exec|script|shell)(_|$)/.test(init.id))
    throw new Error(`${init.id}: actions that run code are forbidden`);
  const spec: ActionSpec = {
    id: init.id,
    title: init.title,
    description: init.description,
    params_schema: init.params_schema,
    risk: init.risk,
    reversible,
    preconditions: init.preconditions ?? [],
    postconditions: init.postconditions ?? [],
    ...(init.guide ? { guide: init.guide } : {}),
  };
  const check: ValidateFunction = ajv.compile(init.params_schema);
  const validate = (params: unknown): P => {
    if (!check(params)) {
      const problems = (check.errors ?? [])
        .slice(0, 5)
        .map((e) => `${e.instancePath || "$"}: ${e.message ?? "invalid"}`);
      throw new WyspError(
        ErrorCode.INVALID_PARAMS,
        `invalid parameters for ${init.id}`,
        { problems },
      );
    }
    return params as P;
  };
  return {
    spec,
    validate,
    async run(params, dryRun = false) {
      const valid = validate(params); // before anything touches the application
      return (await init.handler(valid, dryRun)) ?? {};
    },
  };
}

/** A catalog of actions: answers `adapter.get_actions` and `adapter.execute` from the definitions. */
export class ActionRegistry {
  private readonly actions = new Map<string, RegisteredAction>();

  constructor(
    actions: RegisteredAction[] = [],
    private readonly stateVersion: () => number | Promise<number> = () => 0,
  ) {
    for (const a of actions) this.register(a);
  }

  register(action: RegisteredAction): void {
    if (this.actions.has(action.spec.id))
      throw new Error(`duplicate action ${action.spec.id}`);
    this.actions.set(action.spec.id, action);
  }

  specs(): ActionSpec[] {
    return [...this.actions.values()].map((a) => a.spec);
  }

  /** `params` of `adapter.execute`: `{ call: { action_id, params, dry_run? } }`. Returns an ActionResult. */
  async execute(rpcParams: Record<string, unknown>): Promise<ActionResult> {
    const call = rpcParams.call as
      { action_id?: unknown; params?: unknown; dry_run?: unknown } | undefined;
    if (!call || typeof call.action_id !== "string")
      throw new WyspError(ErrorCode.INVALID_PARAMS, "missing call.action_id");
    const action = this.actions.get(call.action_id);
    if (!action)
      throw new WyspError(
        ErrorCode.ACTION_NOT_FOUND,
        `unknown action ${call.action_id}`,
      );
    const outcome = await action.run(call.params ?? {}, call.dry_run === true);
    return {
      status: "ok",
      changed: [],
      ...outcome,
      state_version: await this.stateVersion(),
    } as ActionResult;
  }
}
