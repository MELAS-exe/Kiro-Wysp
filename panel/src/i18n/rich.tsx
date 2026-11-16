import { Fragment, type ReactNode } from "react";
import { t } from "./index";

/** Like `t`, but `{name}` placeholders are replaced by React nodes (for <kbd>, <code>). */
export function rich(key: string, nodes: Record<string, ReactNode>): ReactNode {
  return t(key)
    .split(/(\{\w+\})/)
    .map((part, i) => {
      const name = /^\{(\w+)\}$/.exec(part)?.[1];
      return (
        <Fragment key={i}>
          {name && name in nodes ? nodes[name] : part}
        </Fragment>
      );
    });
}
