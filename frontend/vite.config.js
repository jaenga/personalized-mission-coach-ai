import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/mission": "http://localhost:8000",
      "/feedback": "http://localhost:8000",
      "/logs": "http://localhost:8000",
      "/chat": "http://localhost:8000",
      "/analysis": "http://localhost:8000",
      "/app-state": "http://localhost:8000",
      "/attendance": "http://localhost:8000",
      "/draw": "http://localhost:8000",
      "/game": "http://localhost:8000",
      "/health-note": "http://localhost:8000",
      "/lessons": "http://localhost:8000",
      "/ranking": "http://localhost:8000",
      "/profile": "http://localhost:8000",
      "/stats": "http://localhost:8000",
      "/verify-student": "http://localhost:8000",
      "/demo-register-student": "http://localhost:8000",
    },
  },
});
