import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server and preview on :3000 to match the Docker setup.
export default defineConfig({
  plugins: [react()],
  server: { port: 3000, strictPort: true },
  preview: { port: 3000, strictPort: true },
});
