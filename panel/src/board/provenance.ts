// The provenance language of panel-ui.md: how each provenance is shown. The border itself lives in styles.css
// under `.wnode.<className>` (and `.swatch.<className>` for the legend).
import type { Provenance } from "../protocol";

export interface ProvenanceStyle {
  className: Provenance;
  /** Short marker shown on the node; observed nodes have none and show the eye icon instead. */
  tag: string | null;
  eye: boolean;
}

export const PROVENANCE_STYLE: Record<Provenance, ProvenanceStyle> = {
  observed: { className: "observed", tag: null, eye: true },
  inferred: { className: "inferred", tag: "likely", eye: false },
  illustrative: { className: "illustrative", tag: "example", eye: false },
};

export function provenanceStyle(p: Provenance): ProvenanceStyle {
  return PROVENANCE_STYLE[p];
}
