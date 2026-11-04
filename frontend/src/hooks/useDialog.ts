import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog behaviour shared by every dialog: Esc closes, Tab stays inside,
 * focus moves in on open and returns to the opener on close.
 * Attach the returned ref to the dialog panel (role="dialog").
 */
export function useDialog<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  onClose: () => void,
) {
  const ref = useRef<T>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const items = () =>
      Array.from(ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) || []).filter(
        (el) => el.offsetParent !== null,
      );
    // A timeout (not requestAnimationFrame) also runs in background tabs.
    const frame = setTimeout(() => {
      const node = ref.current;
      if (node && !node.contains(document.activeElement)) (items()[0] || node).focus();
    }, 0);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
        return;
      }
      if (e.key !== "Tab") return;
      const list = items();
      if (!list.length) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(frame);
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [open]);

  return ref;
}
