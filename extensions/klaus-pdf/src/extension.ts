import * as crypto from "crypto";
import * as vscode from "vscode";

const CORE_URL = process.env.KLAUS_CORE_URL ?? "http://127.0.0.1:7863";
const CORE_TOKEN = process.env.KLAUS_CORE_TOKEN ?? "dev";

interface PdfMeta {
  id: string;
  name: string;
  size: number;
  mtime: number;
}

async function fetchLibrary(): Promise<PdfMeta[]> {
  const res = await fetch(`${CORE_URL}/library`, {
    headers: { "X-Klaus-Token": CORE_TOKEN },
  });
  if (!res.ok) {
    throw new Error(`klaus-core /library returned ${res.status}`);
  }
  const data = (await res.json()) as { pdfs: PdfMeta[] };
  return data.pdfs;
}

function prettyName(name: string): string {
  return name.replace(/\.pdf$/i, "").replace(/_/g, " ");
}

class PdfItem extends vscode.TreeItem {
  constructor(readonly pdf: PdfMeta) {
    super(prettyName(pdf.name));
    this.description = `${(pdf.size / (1024 * 1024)).toFixed(1)} MB`;
    this.tooltip = pdf.name;
    this.iconPath = new vscode.ThemeIcon("file-pdf");
    this.command = {
      command: "klaus.openPdf",
      title: "Open PDF",
      arguments: [pdf],
    };
  }
}

class LibraryProvider implements vscode.TreeDataProvider<PdfItem> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  lastError: string | null = null;

  refresh(): void {
    this.changed.fire();
  }

  getTreeItem(item: PdfItem): vscode.TreeItem {
    return item;
  }

  async getChildren(item?: PdfItem): Promise<PdfItem[]> {
    if (item) {
      return [];
    }
    try {
      const pdfs = await fetchLibrary();
      this.lastError = null;
      return pdfs.map((pdf) => new PdfItem(pdf));
    } catch (e) {
      this.lastError = e instanceof Error ? e.message : String(e);
      return [];
    }
  }
}

function pdfPanelHtml(webview: vscode.Webview, root: vscode.Uri, pdf: PdfMeta): string {
  const js = webview.asWebviewUri(vscode.Uri.joinPath(root, "viewer.js"));
  const css = webview.asWebviewUri(vscode.Uri.joinPath(root, "viewer.css"));
  const worker = webview.asWebviewUri(vscode.Uri.joinPath(root, "pdf.worker.min.mjs"));
  const nonce = crypto.randomBytes(16).toString("base64");
  const csp = [
    "default-src 'none'",
    `style-src ${webview.cspSource} 'unsafe-inline'`,
    `script-src 'nonce-${nonce}'`,
    `connect-src ${CORE_URL} ${webview.cspSource}`,
    "worker-src blob:",
    `img-src ${webview.cspSource} blob: data:`,
  ].join("; ");
  const config = {
    pdfId: pdf.id,
    name: pdf.name,
    coreUrl: CORE_URL,
    coreToken: CORE_TOKEN,
    workerUri: worker.toString(),
  };
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="${css}">
<title>${prettyName(pdf.name)}</title>
</head>
<body>
<div id="root"></div>
<script nonce="${nonce}">window.__KLAUS__ = ${JSON.stringify(config)};</script>
<script nonce="${nonce}" src="${js}"></script>
</body>
</html>`;
}

export function activate(context: vscode.ExtensionContext): void {
  const provider = new LibraryProvider();
  const view = vscode.window.createTreeView("klausLibrary", {
    treeDataProvider: provider,
  });
  const updateMessage = () => {
    view.message = provider.lastError
      ? `klaus-core unreachable (${CORE_URL}): ${provider.lastError}`
      : undefined;
  };
  provider.onDidChangeTreeData(() => setTimeout(updateMessage, 500));
  setTimeout(updateMessage, 1500);

  context.subscriptions.push(
    view,
    vscode.commands.registerCommand("klaus.refreshLibrary", () => provider.refresh()),
    vscode.commands.registerCommand("klaus.openPdf", (pdf: PdfMeta) => {
      const root = vscode.Uri.joinPath(context.extensionUri, "out", "webview");
      const panel = vscode.window.createWebviewPanel(
        "klausPdf",
        prettyName(pdf.name),
        vscode.ViewColumn.Active,
        {
          enableScripts: true,
          retainContextWhenHidden: true,
          localResourceRoots: [root],
        },
      );
      panel.webview.html = pdfPanelHtml(panel.webview, root, pdf);
    }),
  );
}

export function deactivate(): void {}
