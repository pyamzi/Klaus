// Klaus's Excalidraw page. Built into excalidraw.js (an IIFE) by
// scripts/build_excalidraw.sh; edit here, then rebuild.
//
// window.klausExcalidraw:
//   load(sceneJson | null)       replace the scene (null = empty canvas)
//   exportForOcclusion()         -> Promise<string>, JSON
//     {png: <base64>, scene: <excalidraw scene object>, originX, originY,
//      width, height}; origin = getCommonBounds min x/y of the non-deleted
//     elements; PNG = exportToBlob, exportPadding 20, scale 2.
//   occlude()                    export, then send("occlude", result | {error});
//                                the Draw tab's Qt "Use drawing" button calls it
// Python hears pycmd("klausexcal:<action>:<base64 JSON>") for ready, occlude
// and dirty. occlude carries the export result, or {error} when the drawing is
// empty or the export failed (the tab stays open). dirty ({}) is sent once
// after the scene changes from its clean state (the last load or successful
// export); "changed" is the sum of the element versions, so an edit that is
// undone still counts as a change.
// The page lives on the occlusion editor's Draw tab, so Excalidraw's web-app
// chrome is gone: an empty <MainMenu> replaces the default one (and its
// GitHub/X/Discord links), and index.html hides the menu, library and help
// triggers.
import React from "react";
import { createRoot } from "react-dom/client";
import {
  Excalidraw,
  MainMenu,
  exportToBlob,
  getCommonBounds,
  restore,
  serializeAsJSON,
} from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";

const PADDING = 20;
const SCALE = 2;

let api = null;
let cleanVersion = 0;
let reported = false;

function sceneVersion(elements) {
  let v = 0;
  for (const e of elements) v += e.version || 0;
  return v;
}

function markClean(version) {
  cleanVersion = version;
  reported = false;
}

function onChange(elements) {
  if (!api || reported || sceneVersion(elements) === cleanVersion) return;
  reported = true;
  send("dirty", {});
}

function b64(text) {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

// Anki assigns pycmd only after its QWebChannel handshake, which can finish
// after Excalidraw mounts; wait for it (up to 10 s) rather than drop "ready".
function send(action, obj, tries = 0) {
  if (typeof pycmd === "function") pycmd("klausexcal:" + action + ":" + b64(JSON.stringify(obj)));
  else if (tries < 200) setTimeout(() => send(action, obj, tries + 1), 50);
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
  reported = true; // the load itself is no change; markClean below re-arms
  api.resetScene();
  if (sceneJson) {
    const data = restore(JSON.parse(sceneJson), null, null);
    const files = Object.values(data.files || {});
    if (files.length) api.addFiles(files);
    api.updateScene({ elements: data.elements });
    api.scrollToContent(data.elements, { fitToContent: true });
  }
  markClean(sceneVersion(api.getSceneElementsIncludingDeleted()));
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
    const version = api ? sceneVersion(api.getSceneElementsIncludingDeleted()) : 0;
    out = JSON.parse(await exportForOcclusion());
    markClean(version); // Python keeps its own dirty flag until it takes the result
  } catch (e) {
    out = { error: String((e && e.message) || e) };
  }
  send("occlude", out);
}

window.klausExcalidraw = { load, exportForOcclusion, occlude };

function App() {
  return (
    <Excalidraw
      excalidrawAPI={(a) => {
        if (api) return;
        api = a;
        send("ready", {});
      }}
      onChange={onChange}
      aiEnabled={false}
      UIOptions={{
        canvasActions: { loadScene: false, saveToActiveFile: false, export: false },
      }}
    >
      <MainMenu />
    </Excalidraw>
  );
}

createRoot(document.getElementById("root")).render(<App />);
