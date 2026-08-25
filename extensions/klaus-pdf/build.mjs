import { cpSync, mkdirSync } from "fs";
import esbuild from "esbuild";

const watch = process.argv.includes("--watch");

const extensionOpts = {
  entryPoints: ["src/extension.ts"],
  bundle: true,
  platform: "node",
  format: "cjs",
  external: ["vscode"],
  outfile: "out/extension.js",
  sourcemap: true,
};

const webviewOpts = {
  entryPoints: ["webview-src/index.tsx"],
  bundle: true,
  platform: "browser",
  format: "iife",
  outfile: "out/webview/viewer.js",
  sourcemap: true,
};

mkdirSync("out/webview", { recursive: true });
cpSync(
  "node_modules/pdfjs-dist/build/pdf.worker.min.mjs",
  "out/webview/pdf.worker.min.mjs",
);

if (watch) {
  const contexts = await Promise.all([
    esbuild.context(extensionOpts),
    esbuild.context(webviewOpts),
  ]);
  await Promise.all(contexts.map((c) => c.watch()));
  console.log("[klaus-pdf] watching…");
} else {
  await Promise.all([esbuild.build(extensionOpts), esbuild.build(webviewOpts)]);
  console.log("[klaus-pdf] built");
}
