/** Turns the connection status the service worker stores into words a person can act on. */

export interface StatusView {
  tone: "ok" | "wait" | "bad";
  headline: string;
  advice: string;
}

export function describeStatus(
  status: string | undefined,
  detail?: string,
): StatusView {
  const last = detail ? ` Last message: ${detail}` : "";
  switch (status) {
    case "connected":
      return {
        tone: "ok",
        headline: "Connected to the Wysp Core",
        advice:
          "Open the Wysp panel and ask a question about the page you are on.",
      };
    case "connecting":
      return {
        tone: "wait",
        headline: "Connecting...",
        advice: `Waiting for the Core to answer.${last}`,
      };
    case "no_token":
      return {
        tone: "bad",
        headline: "Not connected: no pairing token",
        advice:
          "Paste the contents of ~/.wysp/token in the field above, then press Save.",
      };
    case "bad_url":
      return {
        tone: "bad",
        headline: "Not connected: the Core address is not allowed",
        advice:
          "Use a ws:// address on 127.0.0.1 or localhost, for example ws://127.0.0.1:8765/ws/adapter.",
      };
    case "refused":
      return {
        tone: "bad",
        headline: "Not connected: the Core refused this extension",
        advice: `Check the pairing token. The Core must also be started with WYSP_ALLOWED_ORIGINS set to this extension's origin.${last}`,
      };
    case "disconnected":
    case "stopped":
      return {
        tone: "bad",
        headline: "Not connected",
        advice: `Start the Core with "uv run wysp serve". The extension reconnects by itself.${last}`,
      };
    default:
      return {
        tone: "bad",
        headline: "Not connected",
        advice:
          "The extension has not reported a status yet. Reload it from chrome://extensions, or save the settings.",
      };
  }
}
