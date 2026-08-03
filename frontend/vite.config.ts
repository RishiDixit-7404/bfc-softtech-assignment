/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],

  // Relative asset URLs. StaticFiles is mounted at "/", so "/assets/..." would
  // work too, but relative paths survive being served from a subpath.
  base: "./",

  build: {
    // The whole point of this config. app.py already serves ../ui and is not
    // touched by this phase; the build writes there and the output is
    // committed, so a reviewer needs Python and nothing else. See D27.
    outDir: "../ui",
    emptyOutDir: true,
    // No external host at runtime, so nothing may be left to fetch later.
    assetsInlineLimit: 0,
    sourcemap: false,
  },

  server: {
    port: 5173,
    // Development only. The built page talks to its own origin, so these two
    // lines exist purely so `npm run dev` can reach a locally running app.py.
    proxy: {
      "/session": "http://127.0.0.1:8000",
      "/chat": "http://127.0.0.1:8000",
    },
  },

  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./vitest.setup.ts",
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
