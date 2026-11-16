/** The content script's request handler, independent of chrome.* so that it can be tested on generated DOMs. */
import { ErrorCode, WyspError } from "@wysp/adapter-sdk";
import { applyUndo } from "../actions/undo";
import { runAction } from "../actions/index";
import type { ActionContext } from "../actions/types";
import { originAllowed, originKey } from "../shared/config";
import type {
  CsActionOutcome,
  CsReply,
  CsToSw,
  SwToCs,
} from "../shared/messages";
import { EventTracker } from "./events";
import { pageRef, resolveRef } from "./locators";
import { Launcher } from "./launcher";
import { Overlay } from "./overlay";
import { buildContext, guardedObservation } from "./snapshot";

export class PageAgent {
  readonly overlay: Overlay;
  readonly tracker: EventTracker;
  readonly launcher: Launcher | null;
  private readonly key: string;

  constructor(
    private readonly doc: Document,
    private readonly allowlist: () => readonly string[],
    private readonly send: (message: CsToSw) => void,
    /** Asks the service worker to open the side panel. When absent, no launcher button is shown. */
    openPanel?: () => Promise<boolean>,
    launcherMode: "closed" | "open" = "closed",
  ) {
    this.launcher = openPanel ? new Launcher(doc, openPanel, launcherMode) : null;
    this.key = originKey(doc.location.origin);
    this.overlay = new Overlay(doc, (ref) => {
      if (this.allowed()) this.send({ wyspEvent: "highlight_dismissed", ref });
    });
    this.tracker = new EventTracker({
      doc,
      originKey: this.key,
      allowlist,
      send,
    });
  }

  allowed(): boolean {
    return originAllowed(this.doc.location.origin, this.allowlist());
  }

  start(): void {
    if (!this.allowed()) return;
    this.tracker.start();
    this.launcher?.show();
  }

  stop(): void {
    this.tracker.stop();
    this.overlay.clear();
    this.launcher?.hide();
  }

  private context(): ActionContext {
    return {
      doc: this.doc,
      originKey: this.key,
      allowlist: this.allowlist(),
      resolve: (ref) => resolveRef(this.doc, ref, this.key),
    };
  }

  handle(msg: SwToCs): CsReply {
    try {
      return { ok: true, result: this.dispatch(msg) };
    } catch (err) {
      if (err instanceof WyspError)
        return {
          ok: false,
          code: err.code,
          message: err.message,
          data: err.data,
        };
      return {
        ok: false,
        code: ErrorCode.EXECUTION_FAILED,
        message: err instanceof Error ? err.message : "failed",
      };
    }
  }

  private requireAllowed(): void {
    if (!this.allowed())
      throw new WyspError(
        ErrorCode.PRECONDITION_FAILED,
        "this page is not on the allowlist",
      );
  }

  private dispatch(
    msg: SwToCs,
  ): NonNullable<Extract<CsReply, { ok: true }>["result"]> {
    switch (msg.wysp) {
      case "observe":
        return guardedObservation({
          doc: this.doc,
          originKey: this.key,
          stateVersion: 0,
          allowlist: this.allowlist(),
          scope: msg.scope,
        });
      case "context":
        return buildContext(this.doc, this.key, this.allowed());
      case "execute": {
        this.requireAllowed();
        if (!msg.dryRun) this.tracker.markExecuting();
        const outcome: CsActionOutcome = runAction(
          this.context(),
          msg.actionId,
          msg.params,
          msg.dryRun,
        );
        return outcome;
      }
      case "undo": {
        this.requireAllowed();
        this.tracker.markExecuting();
        const changed = applyUndo(this.context(), msg.record);
        return { status: "ok", changed } satisfies CsActionOutcome;
      }
      case "highlight": {
        this.requireAllowed();
        const ctx = this.context();
        let el: Element =
          msg.ref === pageRef(this.key)
            ? (this.doc.body ?? this.doc.documentElement)
            : ctx.resolve(msg.ref).el;
        const ref = msg.ref;
        this.overlay.show(
          {
            ref,
            durationMs: msg.durationMs,
            getEl: () => {
              if (!el.isConnected) {
                try {
                  el = ctx.resolve(ref).el;
                } catch {
                  return null;
                }
              }
              return el;
            },
          },
          msg.style,
          msg.label,
        );
        return { ok: true };
      }
      case "clear_highlight":
        return { cleared: this.overlay.clear() };
    }
  }
}

