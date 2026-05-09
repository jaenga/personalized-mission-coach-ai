import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/mission": backend,
      "/feedback": backend,
      "/logs": backend,
      "/chat": backend,
      "/analysis": backend,
      "/app-state": backend,
      "/attendance": backend,
      "/draw": backend,
      "/game": backend,
      "/health-note": backend,
      "/lessons": backend,
      "/ranking": backend,
      "/profile": backend,
      "/stats": backend,
      "/students": backend,
      "/verify-student": backend,
      "/demo-register-student": backend,
      "/onboarding-preferences": backend,
      "/mission-review": backend,
      "/mission-ui-actions": backend,
    },
  },
});
