import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  plugins: [tailwindcss(), sveltekit()],
  // Anki's post.ts reads process.env.NODE_ENV.
  define: { "process.env.NODE_ENV": JSON.stringify(mode) },
}));
