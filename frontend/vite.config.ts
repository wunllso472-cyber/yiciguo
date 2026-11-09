import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时把接口转发到后端（uvicorn 默认 8000 端口）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/mock": "http://127.0.0.1:8000",
    },
  },
  build: { target: "es2018", sourcemap: false },
});
