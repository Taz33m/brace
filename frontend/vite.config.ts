import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Matterport SDK key is limited to localhost, so the app is served from there.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5174,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8001", changeOrigin: false, xfwd: true } },
  },
});
