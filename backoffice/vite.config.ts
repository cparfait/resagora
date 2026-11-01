import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// En développement, l'API de gestion tourne sur 127.0.0.1:8000 (runserver, COOKIES_SECURISES=0).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.API_DEV ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: { sourcemap: false, target: "es2023" },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/preparation.ts"],
    css: false,
    coverage: { provider: "v8", include: ["src/**/*.{ts,tsx}"], exclude: ["src/api/schema.d.ts", "src/test/**", "src/main.tsx"] },
  },
});
