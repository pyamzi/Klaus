// Klaus's Excalidraw page. Built into excalidraw.js (an IIFE) by
// scripts/build_excalidraw.sh; edit here, then rebuild.
//
// window.klausExcalidraw:
//   load(sceneJson | null)       replace the scene (null = empty canvas)
//   exportForOcclusion()         -> Promise<string>, JSON
//     {png: <base64>, scene: <excalidraw scene object>, originX, originY,
//      width, height}; origin = getCommonBounds min x/y of the non-deleted
//     elements; PNG = exportToBlob, exportPadding 20, scale 2.
// Python hears pycmd("klausexcal:<action>:<base64 JSON>") for ready, occlude
// and cancel. occlude carries the export result, or {error} when the drawing
// is empty or the export failed (the window stays open).
import React from "react";
import { createRoot } from "react-dom/client";
import {
  Excalidraw,
  exportToBlob,
  getCommonBounds,
  restore,
  serializeAsJSON,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

const PADDING = 20;
const SCALE = 2;

let api = null;

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function send(action, obj) {
  if (typeof pycmd === "function") pycmd("klausexcal:" + action + ":" + b64(JSON.stringify(obj)));
}

function blobBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1]);
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

function load(sceneJson) {
  if (!api) throw new Error("Excalidraw is not ready");
  api.resetScene();
  if (!sceneJson) return;
  const data = restore(JSON.parse(sceneJson), null, null);
  const files = Object.values(data.files || {});
  if (files.length) api.addFiles(files);
  api.updateScene({ elements: data.elements });
  api.scrollToContent(data.elements, { fitToContent: true });
}

async function exportForOcclusion() {
  if (!api) throw new Error("Excalidraw is not ready");
  const elements = api.getSceneElements(); // non-deleted only
  if (!elements.length) throw new Error("empty");
  const appState = api.getAppState();
  const files = api.getFiles();
  const [originX, originY] = getCommonBounds(elements);
  let width = 0;
  let height = 0;
  const blob = await exportToBlob({
    elements,
    appState: { ...appState, exportBackground: true, exportWithDarkMode: false },
    files,
    mimeType: "image/png",
    exportPadding: PADDING,
    getDimensions: (w, h) => {
      width = Math.round(w * SCALE);
      height = Math.round(h * SCALE);
      return { width, height, scale: SCALE };
    },
  });
  const scene = JSON.parse(serializeAsJSON(elements, appState, files, "local"));
  return JSON.stringify({ png: await blobBase64(blob), scene, originX, originY, width, height });
}

async function occlude() {
  let out;
  try {
    out = JSON.parse(await exportForOcclusion());
  } catch (e) {
    out = { error: String((e && e.message) || e) };
  }
  send("occlude", out);
}

window.klausExcalidraw = { load, exportForOcclusion };

function TopRight() {
  return (
    <div className="klaus-actions">
      <button type="button" className="klaus-btn klaus-primary" onClick={occlude}>Occlude</button>
      <button type="button" className="klaus-btn" onClick={() => send("cancel", {})}>Cancel</button>
    </div>
  );
}

function App() {
  return (
    <Excalidraw
      excalidrawAPI={(a) => {
        if (api) return;
        api = a;
        send("ready", {});
      }}
      renderTopRightUI={() => <TopRight />}
      UIOptions={{
        canvasActions: { loadScene: false, saveToActiveFile: false, export: false },
      }}
    />
  );
}

createRoot(document.getElementById("root")).render(<App />);
