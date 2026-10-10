import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The frontend reads only the API, never the store.
    proxy: { "/api": { target: "http://127.0.0.1:8099", rewrite: (p) => p.replace(/^\/api/, "") } },
  },
  build: { chunkSizeWarningLimit: 4000 },
});
