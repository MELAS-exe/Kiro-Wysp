import { CONTRACT_VERSION, type Manifest } from "@wysp/adapter-sdk";

/** The adapter manifest sent in wysp.hello. */
export function buildManifest(browserVersion: string): Manifest {
  return {
    adapter_id: "web-tutor",
    app: { name: "Chrome", version: browserVersion },
    contract_version: CONTRACT_VERSION,
    integration_level: "interface",
    ref_scheme: "web",
    capabilities: [
      "observe",
      "context",
      "actions",
      "execute",
      "undo",
      "highlight",
      "events.state",
      "events.selection",
      "events.user_action",
      "events.navigation",
    ],
    entity_kinds: [
      {
        kind: "page",
        label: "Page",
        description: "The page of the active allowlisted tab",
      },
      {
        kind: "region",
        label: "Region",
        description: "A landmark or named region",
      },
      { kind: "heading", label: "Heading" },
      { kind: "form", label: "Form" },
      {
        kind: "control",
        label: "Control",
        description: "Button, link, field, checkbox, tab...",
      },
      { kind: "dialog", label: "Dialog" },
      { kind: "table", label: "Table" },
      { kind: "list", label: "List" },
      { kind: "chart", label: "Chart" },
      { kind: "status", label: "Status message" },
    ],
    locales: ["en"],
    profile_id: "web-tutor",
    volatile_props: ["bbox"],
  };
}
