import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND = process.env.VITE_BACKEND_URL ?? "http://localhost:8000";
const BACKEND_WS = BACKEND.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
      "/ws": {
        target: BACKEND_WS,
        ws: true,
      },
    },
  },
});
