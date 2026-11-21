import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Modos (cada uno lee su .env.<modo>):
//   npm run dev                -> .env.development (stack local de docker compose)
//   npm run dev -- --mode dev  -> .env.dev  (API Gateway del ambiente dev)
//   npm run dev -- --mode prod -> .env.prod (API Gateway del ambiente prod)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
