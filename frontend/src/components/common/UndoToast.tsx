import { useEffect } from "react";

/** Short-lived confirmation with an undo action, announced to screen readers. */
export function UndoToast({
  message,
  onUndo,
  onDismiss,
  timeoutMs = 6000,
}: {
  message: string;
  onUndo: () => void;
  onDismiss: () => void;
  timeoutMs?: number;
}) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, timeoutMs);
    return () => clearTimeout(timer);
  }, [message, onDismiss, timeoutMs]);
  return (
    <div
      role="status"
      className="fixed bottom-20 lg:bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-lg border border-slate-600 bg-[#172131] px-4 py-3 text-sm text-slate-100 shadow-xl max-w-[calc(100vw-2rem)]"
    >
      <span className="truncate">{message}</span>
      <button
        type="button"
        className="font-semibold text-[#C8AA6E] hover:underline min-h-6"
        onClick={() => {
          onUndo();
          onDismiss();
        }}
      >
        Annulla
      </button>
    </div>
  );
}
