import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  // Served by the Backend Bridge as a single-page app.
  kit: { adapter: adapter({ fallback: "index.html" }) },
};
