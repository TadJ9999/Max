import { defineConfig, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
// The explicit Promise<UserConfig> return type gives the object literal a
// contextual type so `worker.format: "es"` isn't widened to `string` (which
// would fail defineConfig's overload resolution under `tsc -b`).
export default defineConfig(async (): Promise<UserConfig> => ({
  plugins: [react()],

  // Bundle module workers (satellite.js SGP4 propagation) as ES modules.
  worker: { format: "es" },



  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
}));
