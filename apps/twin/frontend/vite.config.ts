import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  base: "./",
  plugins: [react()],
  worker: {
    format: "es",
  },
  optimizeDeps: {
    exclude: ["@relate/relate-wasm"],
  },
  build: {
    outDir: path.resolve(__dirname, "../backend/twin/frontend"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
  server: {
    port: 5174,
    proxy: {
      "/api": "http://127.0.0.1:8002",
    },
  },
});
