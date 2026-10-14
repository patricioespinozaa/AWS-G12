import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /api se redirige a FastAPI (uvicorn api.main:app --port 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { graficos: ["recharts"], react: ["react", "react-dom", "react-router-dom"] } },
    },
  },
});
