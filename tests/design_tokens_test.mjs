// Drift gate for docs/reference/design-tokens.json vs. the CSS that actually
// implements it. If someone edits a color in viewer.css directly instead of
// going through the shared tokens file, this fails — that's the point.
// Run: node --test tests/design_tokens_test.mjs
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { test } from "node:test";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const tokens = JSON.parse(
  readFileSync(join(ROOT, "docs/reference/design-tokens.json"), "utf8"),
);
const css = readFileSync(
  join(ROOT, "extensions/klaus-pdf/webview-src/viewer.css"),
  "utf8",
);

function kebabToCamel(name) {
  return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

/** Custom properties declared in one `{ ... }` block, as { camelCaseKey: value }. */
function parseBlock(selectorPattern) {
  const re = new RegExp(`${selectorPattern}\\s*\\{([^}]*)\\}`);
  const body = re.exec(css)?.[1];
  assert.ok(body, `no ${selectorPattern} block found in viewer.css`);
  const out = {};
  for (const m of body.matchAll(/--([a-z-]+):\s*([^;]+);/g)) {
    out[kebabToCamel(m[1])] = m[2].trim();
  }
  return out;
}

test("viewer.css :root matches design-tokens.json colors.dark", () => {
  assert.deepEqual(parseBlock(":root"), tokens.colors.dark);
});

test("viewer.css body.vscode-light matches design-tokens.json colors.light", () => {
  assert.deepEqual(parseBlock("body\\.vscode-light"), tokens.colors.light);
});

test("highlight ink and alpha match highlights.ts (both read from the same tokens)", () => {
  const src = readFileSync(
    join(ROOT, "extensions/klaus-pdf/webview-src/highlights.ts"),
    "utf8",
  );
  const inks = tokens.highlightInks.map((i) => i.hex);
  const defaultInk = tokens.highlightInks.find((i) => i.default).hex;
  assert.ok(
    src.includes(inks.join('", "')) || inks.every((h) => src.includes(h)),
    "highlights.ts HIGHLIGHT_INKS must contain every ink in design-tokens.json",
  );
  assert.ok(
    src.includes(`DEFAULT_INK = "${defaultInk}"`),
    `highlights.ts DEFAULT_INK must be ${defaultInk}`,
  );
  const { numerator, denominator } = tokens.highlightAlpha;
  assert.ok(
    src.includes(`${numerator} / ${denominator}`),
    `highlights.ts must use the alpha ${numerator}/${denominator} from design-tokens.json`,
  );
});
