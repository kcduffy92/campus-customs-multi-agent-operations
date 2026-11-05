// A deliberate confirm button: hold about one second with a mouse, finger or pen.
// Keyboard and screen-reader users press once to arm it and again within six seconds to confirm.
import { useEffect, useId, useRef, useState } from "react";

export const HOLD_MS = 1000;
const ARM_MS = 6000;

interface Props {
  label: string; // e.g. "APPROVE $2,400.00"
  onConfirm: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: "approve" | "reject" | "danger";
}

export function HoldButton({ label, onConfirm, disabled = false, busy = false, tone = "approve" }: Props) {
  const [progress, setProgress] = useState(0);
  const [armed, setArmed] = useState(false);
  const timer = useRef<number | null>(null);
  const disarm = useRef<number | null>(null);
  const started = useRef(0);
  const hintId = useId();
  const blocked = disabled || busy;

  const clearHold = () => {
    if (timer.current !== null) window.clearInterval(timer.current);
    timer.current = null;
    setProgress(0);
  };
  const clearArm = () => {
    if (disarm.current !== null) window.clearTimeout(disarm.current);
    disarm.current = null;
    setArmed(false);
  };
  useEffect(() => () => { clearHold(); clearArm(); }, []);
  useEffect(() => { if (blocked) { clearHold(); clearArm(); } }, [blocked]);

  const fire = () => { clearHold(); clearArm(); if (!blocked) onConfirm(); };

  const beginHold = () => {
    if (blocked || timer.current !== null) return;
    started.current = Date.now();
    timer.current = window.setInterval(() => {
      const p = Math.min(1, (Date.now() - started.current) / HOLD_MS);
      setProgress(p);
      if (p >= 1) fire();
    }, 30);
  };

  const keyboardPress = () => {
    if (blocked) return;
    if (armed) { fire(); return; }
    setArmed(true);
    disarm.current = window.setTimeout(clearArm, ARM_MS);
  };

  const text = busy ? "PROCESSING…" : armed ? `PRESS AGAIN TO ${label}` : `HOLD TO ${label}`;
  return (
    <>
      <button type="button" className={`hold hold-${tone}${armed ? " armed" : ""}`} disabled={blocked}
        aria-describedby={hintId} aria-busy={busy}
        style={{ ["--p" as string]: progress }}
        onPointerDown={(e) => { if (e.button === 0) beginHold(); }}
        onPointerUp={clearHold} onPointerLeave={clearHold} onPointerCancel={clearHold}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (!e.repeat) keyboardPress(); }
        }}
        onClick={(e) => { if (e.detail === 0) keyboardPress(); /* assistive-tech activation */ }}>
        <span className="hold-fill" aria-hidden="true" />
        <span className="hold-text">{text}</span>
      </button>
      <span id={hintId} className="sr-only">
        Hold for one second, or press Enter twice, to confirm. {armed ? "Armed: press again to confirm." : ""}
      </span>
    </>
  );
}
