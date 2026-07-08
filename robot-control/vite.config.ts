import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": `http://${process.env.OMX_API_HOST || "127.0.0.1"}:${process.env.OMX_API_PORT || "8765"}`
    }
  }
});
