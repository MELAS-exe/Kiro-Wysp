// Tiny static server for the demo dashboard. Loopback only, fixed file list (no path traversal possible).
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT ?? 5180);
const files = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/index.html": ["index.html", "text/html; charset=utf-8"],
  "/app.js": ["app.js", "text/javascript; charset=utf-8"],
  "/style.css": ["style.css", "text/css; charset=utf-8"],
};

createServer(async (req, res) => {
  const hit = files[new URL(req.url ?? "/", "http://localhost").pathname];
  if (!hit) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": hit[1], "cache-control": "no-store" });
  res.end(await readFile(join(root, hit[0])));
}).listen(port, "127.0.0.1", () => console.log(`Haunted Shop Analytics on http://localhost:${port}`));