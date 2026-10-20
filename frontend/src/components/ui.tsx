import { type KeyboardEvent as ReactKeyboardEvent, type ReactNode, useEffect, useRef } from "react";
import { num, tone } from "../lib/format";
import { useStore } from "../store";

/** Status never by colour alone: glyph + word + colour (DESIGN_SYSTEM §12). */
export function Pill({ status, text }: { status: string | null | undefined; text?: string }) {
  const t = tone(status);
  return (
    <span className={`pill s-${t.tone}`}>
      <span aria-hidden>{t.glyph}</span>
      {text ?? t.word}
    </span>
  );
}

export function ToneText({ toneName, children }: { toneName: string; children: ReactNode }) {
  const glyph: Record<string, string> = { ok: "●", info: "○", caution: "▲", warning: "◆", critical: "■", neutral: "—" };
  return (
    <span className={`s-${toneName}`}>
      <span aria-hidden>{glyph[toneName]} </span>
      {children}
    </span>
  );
}

export const Sim = ({ title = "Simulated data" }: { title?: string }) => (
  <span className="sim-badge" title={title}>SIM</span>
);

export function Kpi({ label, value, sub, toneName, large, onClick, bar }: {
  label: string; value: ReactNode; sub?: ReactNode; toneName?: string; large?: boolean; onClick?: () => void;
  /** 0–100: a thin fill bar under the value, in the tile's tone */ bar?: number | null;
}) {
  return (
    <div className={`kpi${large ? " kpi-lg" : ""}`} onClick={onClick} style={onClick ? { cursor: "pointer" } : undefined}>
      {toneName && toneName !== "ok" && toneName !== "neutral" && <span className="kpi-edge" style={{ background: `var(--${toneName})` }} />}
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {bar != null && <div className="kpi-bar" aria-hidden><i style={{ width: `${Math.max(0, Math.min(100, bar))}%`, background: `var(--${toneName ?? "accent"})` }} /></div>}
      {sub !== undefined && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

export function Gauge({ value, max, reserve, reorder }: { value: number; max: number; reserve?: number; reorder?: number }) {
  const pct = Math.max(0, Math.min(100, (100 * value) / Math.max(max, 1)));
  const fill = reserve !== undefined && value < reserve ? "var(--critical)" : reorder !== undefined && value < reorder ? "var(--caution)" : "var(--text-1)";
  return (
    <div className="gauge" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className="gauge-fill" style={{ width: `${pct}%`, background: fill }} />
      {reserve !== undefined && <div className="gauge-tick" style={{ left: `${(100 * reserve) / max}%`, background: "var(--critical)" }} title="Reserve" />}
      {reorder !== undefined && <div className="gauge-tick" style={{ left: `${(100 * reorder) / max}%`, background: "var(--caution)" }} title="Reorder level" />}
    </div>
  );
}

/** Keyboard activation for a clickable element that isn't a button (Enter or Space, like a button). */
export const onActivate = (fn: () => void) => (e: ReactKeyboardEvent) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fn();
  }
};

export function Row({ label, value, extra, onClick }: { label: ReactNode; value?: ReactNode; extra?: ReactNode; onClick?: () => void }) {
  return (
    <div className={`row${extra === undefined ? " row-2" : ""}${onClick ? " row-click" : ""}`} onClick={onClick}
      {...(onClick ? { role: "button", tabIndex: 0, onKeyDown: onActivate(onClick) } : {})}>
      <span className="row-label">{label}</span>
      {extra !== undefined && <span>{extra}</span>}
      <span className="row-value">{value}</span>
    </div>
  );
}

export const N = ({ v, d = 0 }: { v: unknown; d?: number }) => <span className="mono">{num(v, d)}</span>;

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [onClose]);
  useEffect(() => {          // focus moves into the dialog, Tab stays inside it, and returns to the opener on close
    const opener = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(box.current?.querySelectorAll<HTMLElement>(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])") ?? []).filter((x) => !x.hasAttribute("disabled"));
    (focusables().find((x) => !x.classList.contains("close")) ?? focusables()[0])?.focus();
    const trap = (e: KeyboardEvent) => {
      const f = focusables();
      if (e.key !== "Tab" || !f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    };
    addEventListener("keydown", trap);
    return () => { removeEventListener("keydown", trap); opener?.focus?.(); };
  }, []);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={box}>
        <div className="card-title" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: "var(--t-h2)" }}>{title}</h2>
          <button className="close" onClick={onClose} aria-label="Close">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Toasts() {
  const { toasts, set } = useStore();
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.severity === "CRITICAL" ? " critical" : t.severity === "INFO" ? " info" : ""}`}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <span><ToneText toneName={t.severity === "CRITICAL" ? "critical" : t.severity === "INFO" ? "info" : "warning"}>{t.text}</ToneText></span>
            <button className="close" aria-label="Dismiss" onClick={() => set({ toasts: toasts.filter((x) => x.id !== t.id) })}>×</button>
          </div>
        </div>
      ))}
    </div>
  );
}

export const Loading = () => <div className="empty">Loading…</div>;
export const ErrorText = ({ error }: { error: unknown }) => (
  <div className="error-text">■ {error instanceof Error ? error.message : "Something went wrong."}</div>
);
