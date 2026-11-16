import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "happy-dom",
    environmentOptions: { happyDOM: { url: "http://localhost:5180/" } },
    include: ["tests/**/*.test.ts"],
    // Tests that need a real Chrome live in tests/live and run on demand (npm run test:live).
    exclude: ["tests/live/**", "node_modules/**"],
  },
});