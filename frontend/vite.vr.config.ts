import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// A second dev server for the phone in the headset. Phones only expose motion sensors to
// secure pages, so this one is HTTPS (self-signed) and listens on the local network.
// The laptop keeps using the plain http://localhost:5174 server.
const port = Number(process.env.BRACE_VR_PORT ?? 5175);

export default defineConfig({
  plugins: [react(), basicSsl()],
  cacheDir: `node_modules/.vite-vr-${port}`,      // its own dependency cache: see vite.config.ts
  server: {
    host: true,
    port,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${process.env.BRACE_API_PORT ?? 8001}`, changeOrigin: false, xfwd: true } },
  },
});
