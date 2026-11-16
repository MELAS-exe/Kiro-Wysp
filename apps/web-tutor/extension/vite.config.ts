import { defineConfig } from "vite";

// Two builds (see package.json): the default builds the service worker (ES module) and the options page;
// `--mode content` builds the content script as a single classic script (content scripts cannot be modules).
export default defineConfig(({ mode }) => {
  const content = mode === "content";
  const input: Record<string, string> = content
    ? { content: "src/cs/content.ts" }
    : { background: "src/sw/background.ts", options: "src/options/options.ts", sidepanel: "src/sidepanel/sidepanel.ts" };
  return {
    publicDir: content ? false : "public",
    build: {
      outDir: "dist",
      emptyOutDir: !content,
      target: "es2022",
      minify: false,
      sourcemap: false,
      rollupOptions: {
        input,
        output: {
          entryFileNames: "[name].js",
          chunkFileNames: "chunks/[name].js",
          format: content ? "iife" : "es",
        },
      },
    },
  };
});
