import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Application des gardiens : servie sur le LAN (option A) ou par la DMZ (option B), fonctionne hors ligne.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: { "/api": { target: process.env.API_DEV ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: { sourcemap: false, target: "es2023" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/preparation.ts"],
    css: false,
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/test/**", "src/main.tsx"] },
  },
});
