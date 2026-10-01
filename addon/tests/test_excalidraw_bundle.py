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

D = os.path.join(ROOT, "klausmate", "image_occlusion", "excalidraw")
ASSET_PATH = "/_addons/klausmate/image_occlusion/excalidraw/"
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

section("asset path")
check("EXCALIDRAW_ASSET_PATH is the add-on's own folder",
      re.search(r'window\.EXCALIDRAW_ASSET_PATH\s*=\s*"' + re.escape(ASSET_PATH) + '"', html))
check("index.html loads the bundle as a classic script",
      '<script src="excalidraw.js"></script>' in html and 'type="module"' not in html)

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
init = open(os.path.join(ROOT, "klausmate", "__init__.py"), encoding="utf-8").read()
pattern = re.search(r'setWebExports\(.*?r"([^"]+)"', init, re.S).group(1)
unserved = []
for dirpath, _, files in os.walk(D):
    for n in files:
        rel = os.path.relpath(os.path.join(dirpath, n), os.path.join(ROOT, "klausmate"))
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
