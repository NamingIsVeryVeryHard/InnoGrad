import { defineConfig } from "vite";

export default defineConfig({
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: {
    target: "esnext",
    rollupOptions: { input: ["index.html", "prototype/index.html"] },
  },
});
