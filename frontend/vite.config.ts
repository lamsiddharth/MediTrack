import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
  server: {
    port: 5173,
    // In development the API runs as a separate process. Proxying it under the
    // same origin keeps the session cookie working and means there is no CORS
    // configuration here that would not exist in production, where nginx does
    // exactly the same job.
    proxy: {
      "/api": { target: "http://127.0.0.1:9000", changeOrigin: true },
      "/healthz": { target: "http://127.0.0.1:9000", changeOrigin: true },
    },
  },
});
