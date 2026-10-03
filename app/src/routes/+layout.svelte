<script lang="ts">
  import "../app.css";
  import { Toaster } from "$lib/components/ui/sonner";

  let { children } = $props();
</script>

<!-- "system": Klaus follows the OS appearance; mode-watcher isn't used. -->
<Toaster theme="system" />
{@render children()}
