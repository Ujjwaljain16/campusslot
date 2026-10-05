import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In development the Vite server stands in for nginx / the Ingress and forwards /api.
    proxy: { "/api": "http://localhost:8000" },
  },
});
