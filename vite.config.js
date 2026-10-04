import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

// 本の画像（images/）とデータ（data/）は、これまでどおりリポジトリ直下に置いたまま配信する。
// 開発中はそのまま返し、ビルド時は dist/ にコピーする。
const STATIC_DIRS = ["images", "data"];
const MIME = { ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".csv": "text/csv; charset=utf-8", ".json": "application/json; charset=utf-8" };

function repoStatic() {
  const root = process.cwd();
  return {
    name: "repo-static",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = decodeURIComponent((req.url || "").split("?")[0]);
        const top = url.split("/")[1];
        if (!STATIC_DIRS.includes(top)) return next();
        const file = path.join(root, url);
        if (!file.startsWith(path.join(root, top)) || !fs.existsSync(file) || !fs.statSync(file).isFile()) return next();
        res.setHeader("Content-Type", MIME[path.extname(file).toLowerCase()] || "application/octet-stream");
        res.setHeader("Cache-Control", "no-cache");
        fs.createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      for (const d of STATIC_DIRS) {
        if (fs.existsSync(path.join(root, d))) fs.cpSync(path.join(root, d), path.join(root, "dist", d), { recursive: true });
      }
    },
  };
}

export default defineConfig({
  base: "./",                      // GitHub Pages のサブパスでも動くよう相対パスにする
  plugins: [react(), repoStatic()],
  server: { port: 5173 },
});
