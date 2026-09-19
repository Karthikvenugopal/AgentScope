import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const target = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/api", "/health", "/ready", "/openapi.json"].map((path) => [
        path,
        { target },
      ]),
    ),
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
