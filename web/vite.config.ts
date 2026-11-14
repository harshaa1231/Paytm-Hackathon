import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy the API to uvicorn on :8000. In prod the API serves this app from the same origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/v1": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000", "/docs": "http://127.0.0.1:8000", "/openapi.json": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
