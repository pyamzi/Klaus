"""Image Occlusion 3/3: the vendored Excalidraw page loads with no network.

Built by scripts/build_excalidraw.sh. Run:
env QT_QPA_PLATFORM=offscreen python3 tests/test_excalidraw_bundle.py
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".claude/skills/klaus-test/scripts"))
from anki_stubs import check, section, report  # noqa: E402

D = os.path.join(ROOT, "klaus_note", "image_occlusion", "excalidraw")
ASSET_PATH = "/_addons/klaus_note/image_occlusion/excalidraw/"
MAX_BYTES = 8 * 1024 * 1024
LOCAL = {"127.0.0.1", "localhost"}
# Hosts 0.18.1's own code names. None is fetched unless the user acts (a help
# link, "Browse libraries", a pasted embed link, the shareable-link and AI
# dialogs); the page never shows those links offline. Licence-comment URLs
# live in excalidraw.js.LEGAL.txt, which is not scanned. A version bump that
# adds a host fails here, so it gets looked at.
INERT = {
    "www.w3.org",  # xmlns
    "github.com", "docs.excalidraw.com", "discord.gg", "x.com",
    "youtube.com", "plus.excalidraw.com", "app.excalidraw.com",  # help links
    "libraries.excalidraw.com",  # "Browse libraries" button
    "json.excalidraw.com", "oss-collab.excalidraw.com", "oss-ai.excalidraw.com",
    "excalidraw-room-persistence.firebaseio.com",
    "us-central1-excalidraw-room-persistence.cloudfunctions.net",  # share/AI/collab
    "www.youtube.com", "player.vimeo.com", "www.figma.com", "twitter.com",
    "platform.twitter.com", "reddit.com", "embed.reddit.com", "gist.github.com",
    "giphy.com",  # embeds of a link the user pastes
    "mermaid.js.org", "reactjs.org",  # docs links in messages
}
CDNS = ("esm.sh", "unpkg.com", "jsdelivr.net", "cdnjs", "googleapis.com")


def read(name):
    with open(os.path.join(D, name), encoding="utf-8") as f:
        return f.read()


def hosts(text):
    return set(re.findall(r"https?://([A-Za-z0-9.-]+)", text))


section("files")
for name in ("index.html", "excalidraw.js", "excalidraw.css", "entry.jsx",
             "LICENSE-excalidraw.txt", "LICENSE-react.txt"):
    check(name + " exists", os.path.isfile(os.path.join(D, name)))
fonts = os.path.join(D, "fonts")
check("fonts/Excalifont has woff2 files", os.path.isdir(os.path.join(fonts, "Excalifont"))
      and any(n.endswith(".woff2") for n in os.listdir(os.path.join(fonts, "Excalifont"))))
if not os.path.isfile(os.path.join(D, "excalidraw.js")):
    raise SystemExit(report())

html, js, css = read("index.html"), read("excalidraw.js"), read("excalidraw.css")

section("asset path: the page's own folder, whatever the add-on folder is called")
check("index.html names no add-on folder (no /_addons/klaus_note)", "/_addons/" not in html)
m = re.search(r"<script>(window\.EXCALIDRAW_ASSET_PATH\s*=[^<]*)</script>", html)
check("EXCALIDRAW_ASSET_PATH is set in an inline script before the bundle",
      m is not None and html.find(m.group(0)) < html.find('src="excalidraw.js"'))
_node = shutil.which("node") or shutil.which("node", path=os.path.expanduser("~/.local/bin"))
if m is not None and _node:
    for page in (ASSET_PATH + "index.html", "/_addons/1374772155/image_occlusion/excalidraw/index.html"):
        probe = ("var window = {}, location = {pathname: %r, href: 'http://127.0.0.1:1' + %r};"
                 "%s; process.stdout.write(window.EXCALIDRAW_ASSET_PATH)" % (page, page, m.group(1)))
        r = subprocess.run([_node, "-e", probe], capture_output=True, text=True, timeout=30)
        check("served from %s: the asset path is its folder" % page,
              r.stdout == page[: page.rindex("/") + 1], r.stdout + r.stderr[-200:])
elif m is not None:
    print("  SKIP asset-path evaluation: node not found")
check("index.html loads the bundle as a classic script",
      '<script src="excalidraw.js"></script>' in html and 'type="module"' not in html)

section("layout: the tool bar runs down the right edge (Pouya, 2026-10-01)")
_desk = ".excalidraw:not(.excalidraw--mobile)"
check("the shapes bar is pinned to the right and centred, desktop layout only",
      _desk + " .shapes-section {" in html
      and "position: fixed; top: 0; bottom: 0; right: 16px;" in html.split(_desk + " .shapes-section {")[1].split("}")[0])
check("its tools stack in one column",
      "grid-auto-flow: row;" in html.split(_desk + " .App-toolbar > .Stack_horizontal {")[1].split("}")[0])
check("the extra-tools menu opens to the bar's left, never off the bottom",
      "right: calc(100% + 12px)" in html.split(_desk + " .App-toolbar__extra-tools-dropdown {")[1].split("}")[0])
check("no rule restyles the mobile layout (Excalidraw's own bar stays there)",
      all(line.lstrip().startswith(_desk) for line in html.splitlines()
          if line.lstrip().startswith(".excalidraw") and "{" in line))

section("no network")
XMLNS = {"www.w3.org"}
check("index.html names no remote URL", not hosts(html) - LOCAL - XMLNS, str(hosts(html)))
check("excalidraw.css names no remote URL but xmlns", not hosts(css) - LOCAL - XMLNS, str(hosts(css)))
extra = hosts(js) - LOCAL - INERT
check("excalidraw.js names only known, user-initiated hosts", not extra, str(sorted(extra)))
check("no CDN anywhere (the font fallback is patched to the asset path)",
      not any(c in html + js + css for c in CDNS))
missing = [u for u in re.findall(r"url\([\"']?([^)\"']+)", css)
           if not u.startswith("data:") and not os.path.isfile(os.path.join(D, u))]
check("every font the stylesheet names is shipped", not missing, str(missing[:3]))
js_missing = [u for u in set(re.findall(r"\./fonts/[^\"'`)\s]*\.woff2", js))
              if not os.path.isfile(os.path.join(D, u))]
check("every ./fonts/ woff2 the bundle names is shipped", not js_missing, str(js_missing[:3]))
licenses = os.path.join(fonts, "LICENSES.txt")
check("fonts/LICENSES.txt exists", os.path.isfile(licenses))
FAMILIES = ("Assistant", "Cascadia", "ComicShanns", "Excalifont", "Liberation",
            "Lilita", "Nunito", "Virgil", "Xiaolai")
lic_text = open(licenses, encoding="utf-8").read() if os.path.isfile(licenses) else ""
check("fonts/LICENSES.txt names all 9 families, one folder each",
      all(f in lic_text and os.path.isdir(os.path.join(fonts, f)) for f in FAMILIES),
      str([f for f in FAMILIES if f not in lic_text]))

section("served by Anki")
init = open(os.path.join(ROOT, "klaus_note", "__init__.py"), encoding="utf-8").read()
pattern = re.search(r'setWebExports\(.*?r"([^"]+)"', init, re.S).group(1)
unserved = []
for dirpath, _, files in os.walk(D):
    for n in files:
        rel = os.path.relpath(os.path.join(dirpath, n), os.path.join(ROOT, "klaus_note"))
        if not n.endswith((".txt", ".jsx")) and not re.fullmatch(pattern, rel.replace(os.sep, "/")):
            unserved.append(rel)
check("the web-exports regex serves every page file", not unserved, str(unserved[:3]))

section("size")
size = os.path.getsize(os.path.join(D, "excalidraw.js"))
print("  excalidraw.js: %d bytes (%.2f MB)" % (size, size / 1024 / 1024))
check("bundle under 8 MB", size < MAX_BYTES, str(size))

section("page API")
check("bundle sets window.klausExcalidraw with load and exportForOcclusion",
      "window.klausExcalidraw=" in js and "exportForOcclusion" in js and "load" in js)
check("bundle posts klausexcal:<action>", "klausexcal:" in js)
node = shutil.which("node") or shutil.which("node", path=os.path.expanduser("~/.local/bin"))
if node:
    probe = ("const src=require('fs').readFileSync(process.argv[1],'utf8');"
             "new Function(src);"  # parses as a classic script
             "process.stdout.write('ok')")
    r = subprocess.run([node, "-e", probe, os.path.join(D, "excalidraw.js")],
                       capture_output=True, text=True)
    check("node parses the bundle as a classic script", r.stdout == "ok", r.stderr[-300:])
else:
    print("  SKIP node parse check: node not found")

raise SystemExit(report())
