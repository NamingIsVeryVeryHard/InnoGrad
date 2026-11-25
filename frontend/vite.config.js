import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  build: {
    target: "esnext",
    rollupOptions: { input: ["index.html", "prototype/index.html"] },
  },
});
