import * as crypto from "crypto";
import * as vscode from "vscode";

const CORE_URL = process.env.KLAUS_CORE_URL ?? "http://127.0.0.1:7863";
const CORE_TOKEN = process.env.KLAUS_CORE_TOKEN ?? "dev";
// Same default klausmate/plus.py and klaus-core/embeddings.py already use —
// one shared subscription, one base URL, kept in sync by convention.
const PLUS_BASE = process.env.KLAUS_PLUS_BASE ?? "https://klausmate.com";
const PLUS_KEY_SECRET = "klausPlusKey";

interface PdfMeta {
  id: string;
  name: string;
  size: number;
  mtime: number;
}

// Every klaus-core request carries this; the Plus key rides along when one
// is signed in so a future endpoint (KB-004's /search) can route through
// it via embeddings.config_from_header() — nothing reads it yet.
async function coreHeaders(context: vscode.ExtensionContext): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "X-Klaus-Token": CORE_TOKEN };
  const plusKey = await context.secrets.get(PLUS_KEY_SECRET);
  if (plusKey) {
    headers["X-Klaus-Plus-Key"] = plusKey;
  }
  return headers;
}

async function fetchLibrary(context: vscode.ExtensionContext): Promise<PdfMeta[]> {
  const res = await fetch(`${CORE_URL}/library`, { headers: await coreHeaders(context) });
  if (!res.ok) {
    throw new Error(`klaus-core /library returned ${res.status}`);
  }
  const data = (await res.json()) as { pdfs: PdfMeta[] };
  return data.pdfs;
}

// POST /v1/login and, on success, store the returned key — same
// device-scoped-key contract klausmate/plus.py's login() uses against the
// same service, so signing in here never revokes klausmate's session or
// vice versa. Returns true on success.
async function signIn(context: vscode.ExtensionContext): Promise<boolean> {
  const email = await vscode.window.showInputBox({
    prompt: "Klaus Plus email",
    placeHolder: "you@example.com",
    ignoreFocusOut: true,
  });
  if (!email) {
    return false;
  }
  const password = await vscode.window.showInputBox({
    prompt: "Klaus Plus password",
    password: true,
    ignoreFocusOut: true,
  });
  if (!password) {
    return false;
  }
  try {
    const res = await fetch(`${PLUS_BASE}/v1/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, device: "klausbook" }),
    });
    if (!res.ok) {
      vscode.window.showErrorMessage("Klaus Plus sign in failed — check your email and password.");
      return false;
    }
    const data = (await res.json()) as { key?: string };
    if (!data.key) {
      vscode.window.showErrorMessage("Klaus Plus sign in failed — no key returned.");
      return false;
    }
    await context.secrets.store(PLUS_KEY_SECRET, data.key);
    vscode.window.showInformationMessage("Signed in to Klaus Plus.");
    return true;
  } catch (e) {
    vscode.window.showErrorMessage(
      `Klaus Plus sign in failed: ${e instanceof Error ? e.message : String(e)}`,
    );
    return false;
  }
}

// Best-effort revoke on the service (this device's key only — klausmate's
// or another machine's session is untouched), then always forget the key
// locally: a network failure must not strand a "signed in" state the user
// can no longer act on.
async function signOut(context: vscode.ExtensionContext): Promise<void> {
  const key = await context.secrets.get(PLUS_KEY_SECRET);
  if (key) {
    try {
      await fetch(`${PLUS_BASE}/v1/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      });
    } catch {
      // best-effort — still clear the local key below
    }
  }
  await context.secrets.delete(PLUS_KEY_SECRET);
  vscode.window.showInformationMessage("Signed out of Klaus Plus.");
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

  constructor(private readonly context: vscode.ExtensionContext) {}

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
      const pdfs = await fetchLibrary(this.context);
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
    `img-src ${webview.cspSource} ${CORE_URL} blob: data:`,
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
  const panels = new Map<string, vscode.WebviewPanel>();
  const provider = new LibraryProvider(context);
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
    vscode.commands.registerCommand("klaus.signIn", async () => {
      if (await signIn(context)) {
        provider.refresh();
      }
    }),
    vscode.commands.registerCommand("klaus.signOut", async () => {
      await signOut(context);
      provider.refresh();
    }),
    vscode.commands.registerCommand("klaus.openPdf", (pdf: PdfMeta) => {
      // One panel per PDF: a second panel would hold its own copy of the
      // notes doc and last-write-wins autosave would clobber edits.
      const existing = panels.get(pdf.id);
      if (existing) {
        existing.reveal(vscode.ViewColumn.Active);
        return;
      }
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
      panels.set(pdf.id, panel);
      panel.onDidDispose(() => panels.delete(pdf.id));
      panel.webview.html = pdfPanelHtml(panel.webview, root, pdf);
    }),
  );
}

export function deactivate(): void {}
