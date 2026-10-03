export function keyIsTaken(event: KeyboardEvent): boolean {
  return event.defaultPrevented || event.isComposing ||
    (event.target instanceof Element && event.target.closest(
      'input, textarea, select, [contenteditable], dialog, [role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [data-sonner-toaster]',
    ) !== null);
}
