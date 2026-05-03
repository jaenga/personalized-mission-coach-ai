import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/mission": "http://127.0.0.1:8000",
      "/feedback": "http://127.0.0.1:8000",
      "/logs": "http://127.0.0.1:8000",
      "/chat": "http://127.0.0.1:8000",
      "/analysis": "http://127.0.0.1:8000",
      "/profile": "http://127.0.0.1:8000",
      "/verify-student": "http://127.0.0.1:8000",
      "/demo-register-student": "http://127.0.0.1:8000",
    },
  },
});
