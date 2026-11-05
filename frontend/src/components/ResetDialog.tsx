// Reset the working database from the untouched original. Needs the word RESET typed in.
import { useEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  blocked: string | null;
  onClose: () => void;
  onReset: () => Promise<{ ok: boolean; message: string }>;
}

export function ResetDialog({ open, blocked, onClose, onReset }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      setTyped(""); setResult(null);
      if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
    }
    if (!open && d.open) { if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }
  }, [open]);

  const go = async () => {
    if (busy || typed !== "RESET" || blocked) return;
    setBusy(true);
    try { setResult(await onReset()); } finally { setBusy(false); }
  };

  return (
    <dialog ref={ref} className="reset-dialog pixel-box" aria-labelledby="reset-title" onCancel={onClose} onClose={onClose}>
      <h2 id="reset-title">Reset the shop?</h2>
      <p>This copies the original database over the working copy: $3,400 in checking, all three tickets open, no
        approval requests. The audit history is kept; a reset marker starts a fresh round.</p>
      {blocked && <p className="notice warn">{blocked}</p>}
      <label>
        <span>Type RESET to confirm</span>
        <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" aria-describedby="reset-help" />
      </label>
      <p id="reset-help" className="muted small">Capital letters, exactly RESET.</p>
      {result && <p className={`notice ${result.ok ? "ok" : "danger"}`} role="alert">{result.message}</p>}
      <div className="dialog-actions">
        <button type="button" className="btn ghost" onClick={onClose}>{result?.ok ? "Close" : "Cancel"}</button>
        <button type="button" className="btn danger" onClick={go} disabled={busy || typed !== "RESET" || !!blocked || !!result?.ok}>
          {busy ? "RESETTING…" : "RESET DATABASE"}
        </button>
      </div>
    </dialog>
  );
}
