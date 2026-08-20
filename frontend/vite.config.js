import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  base: "/",
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});