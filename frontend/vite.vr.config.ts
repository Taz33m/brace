import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// A second dev server for the phone in the headset. Phones only expose motion sensors to
// secure pages, so this one is HTTPS (self-signed) and listens on the local network.
// The laptop keeps using the plain http://localhost:5174 server.
export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    host: true,
    port: 5175,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8001", changeOrigin: true } },
  },
});
