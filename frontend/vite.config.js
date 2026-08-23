import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes to dist/ -- app/main.py mounts this directory.
// During local dev, /api/* proxies to FastAPI running on :8000
// (`uvicorn app.main:app --reload` from the repo root, separately from
// `npm run dev` here) so you don't need CORS config for local iteration.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
