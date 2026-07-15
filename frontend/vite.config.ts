/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// https://vitejs.dev/config/
//
// The dev-server proxy target is read from
// ``VITE_API_PROXY_TARGET`` so operators can run the
// frontend against a non-default FastAPI host / port without
// editing this file. The default (``http://127.0.0.1:8000``)
// matches the v0.3 backend startup script. The variable is
// read at config time; Vite does not pick up changes to
// ``process.env`` after the dev server has started.
const apiProxyTarget = (() => {
  const fromEnv = process.env.VITE_API_PROXY_TARGET;
  if (typeof fromEnv === "string" && fromEnv.trim()) {
    return fromEnv.trim().replace(/\/+$/, "");
  }
  return "http://127.0.0.1:8000";
})();

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
  port: 5173,
  strictPort: true,
  proxy: {
    "/api": {
      target: apiProxyTarget,
      changeOrigin: true,
    },
  },
},
preview: {
    port: 5173,
  },
  build: {
    sourcemap: true,
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
  },
});
