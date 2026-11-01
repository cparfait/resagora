import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Le portail ne parle qu'à la façade DMZ (/api/portail/*) ; en développement, façade locale sur 127.0.0.1:8080.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    proxy: { "/api/portail": { target: process.env.FACADE_DEV ?? "http://127.0.0.1:8080", changeOrigin: false } },
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
