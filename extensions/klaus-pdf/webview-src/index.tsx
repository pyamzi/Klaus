import { createRoot } from "react-dom/client";
import * as pdfjs from "pdfjs-dist";
import ImpressView from "./ImpressView";
import "./viewer.css";

declare global {
  interface Window {
    __KLAUS__: {
      pdfId: string;
      name: string;
      coreUrl: string;
      coreToken: string;
      workerUri: string;
    };
  }
}

async function main() {
  const cfg = window.__KLAUS__;
  // The webview CSP only allows blob: workers, so load the worker source
  // from its webview URI and hand pdf.js a blob URL.
  const source = await fetch(cfg.workerUri).then((r) => r.text());
  pdfjs.GlobalWorkerOptions.workerSrc = URL.createObjectURL(
    new Blob([source], { type: "text/javascript" }),
  );
  createRoot(document.getElementById("root")!).render(
    <ImpressView pdfId={cfg.pdfId} name={cfg.name} />,
  );
}

main();
