import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI is same-origin in production (FastAPI serves the build in Phase 6).
// In dev, proxy API + WebSocket to the Atrium server so there's no CORS dance.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8775", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8775", ws: true },
    },
  },
  build: { outDir: "dist" },
});
