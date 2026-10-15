import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Evita depender de @types/node: solo se usa process.env en esta configuración.
declare const process: { env: Record<string, string | undefined> };

// La API local (python -m servidor) escucha solo en 127.0.0.1; el puerto sigue a
// COPILOTO_PUERTO (por defecto 8000), igual que el servidor.
const puertoApi = process.env.COPILOTO_PUERTO || "8000";
const proxy = { "/api": { target: `http://127.0.0.1:${puertoApi}` } };

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
});
