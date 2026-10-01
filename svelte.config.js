import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  kit: {
    // Served by the Backend Bridge as a single-page app.
    adapter: adapter({ fallback: "index.html" }),
    // Anki's pages own /_app on the same origin.
    appDir: "_klaus",
    // Same alias Anki uses for its generated TS library (scripts/gen-ts.sh).
    alias: { "@generated": "vendor/anki/out/ts/lib/generated" },
  },
};
