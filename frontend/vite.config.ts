import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_PROXY_TARGET = process.env.VITE_API_PROXY_TARGET || "http://localhost:8001";

export default defineConfig(() => ({
  plugins: [react()],
  base: "/",
  server: {
    port: 8000,
    strictPort: true,
    proxy: {
      "/health": {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
      "/ingest_products": {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
      "/recommend": {
        target: API_PROXY_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
}));
