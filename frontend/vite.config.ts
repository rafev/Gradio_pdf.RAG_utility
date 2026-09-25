import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` proxies the API to the Python server (python -m paper_rag.api [--public]).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        admin: "admin.html",
      },
    },
    chunkSizeWarningLimit: 2000,
  },
  server: {
    // 127.0.0.1 (not localhost) so cookies set by the API/admin ports are sent through the proxy.
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
      "/admin/api": { target: "http://127.0.0.1:8001", changeOrigin: false },
    },
  },
  test: {
    environment: "node",
  },
});
