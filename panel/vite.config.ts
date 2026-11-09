import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The Core serves the built Panel at http://127.0.0.1:8765 (same origin as its WebSocket).
// In development, `npm run dev` serves on :5173 and the Panel connects to the Core on :8765.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
