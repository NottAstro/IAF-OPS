import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const api = `http://127.0.0.1:${env.API_PORT || "8010"}`;
  return {
    envDir: "..",
    plugins: [react()],
    server: { port: 5173, strictPort: true, proxy: { "/api": { target: api, ws: true, changeOrigin: false } } },
    build: { chunkSizeWarningLimit: 3000 },
  };
});
