import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Matterport SDK key is limited to localhost, so the app is served from there.
const port = Number(process.env.BRACE_WEB_PORT ?? 5174);

export default defineConfig({
  plugins: [react()],
  // Each dev server keeps its own dependency cache. Sharing one let the laptop's and the phone's servers
  // overwrite each other's on start, and the page then loaded blank.
  cacheDir: `node_modules/.vite-web-${port}`,
  server: {
    host: "localhost",
    port,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${process.env.BRACE_API_PORT ?? 8001}`, changeOrigin: false, xfwd: true } },
  },
});
