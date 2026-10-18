import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./SettingsWindow.css";

/** Interactive settings open beside their heading, rather than expanding the settings list. */
export function SettingsWindow({ title, meta, children, open, onOpen, onClose }: {
  title: string; meta?: string; children: ReactNode; open: boolean; onOpen: () => void; onClose: () => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const pinned = useRef(false);
  const focusOnOpen = useRef(false);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const cancel = () => clearTimeout(timer.current);
  const close = (restoreFocus = false) => {
    cancel(); onClose();
    if (restoreFocus) trigger.current?.focus();
  };
  const show = (focus = false) => {
    cancel(); pinned.current = focus; focusOnOpen.current = focus; onOpen();
    if (focus && open) panel.current?.focus();
  };
  const leave = () => {
    cancel();
    if (!pinned.current) timer.current = setTimeout(() => close(), 250);
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!open) { setPosition(null); return; }
    const place = () => {
      if (!trigger.current || !panel.current) return;
      const r = trigger.current.getBoundingClientRect(), p = panel.current.getBoundingClientRect();
      const left = r.right + 10 + p.width <= innerWidth - 8 ? r.right + 10 : r.left - p.width - 10;
      setPosition({ left: Math.max(8, Math.min(left, innerWidth - p.width - 8)), top: Math.max(8, Math.min(r.top, innerHeight - p.height - 8)) });
    };
    place();
    const observer = new ResizeObserver(place);
    if (panel.current) observer.observe(panel.current);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open]);
  useLayoutEffect(() => {
    if (open && position && focusOnOpen.current) {
      const control = panel.current?.querySelector<HTMLElement>(".settings-window-body button:not(:disabled), .settings-window-body input, .settings-window-body a");
      (control ?? panel.current)?.focus();
      focusOnOpen.current = false;
    }
  }, [open, position]);
  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => {
      if (e.target instanceof Node && !trigger.current?.contains(e.target) && !panel.current?.contains(e.target)) close();
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open, onClose]);
  return <section className="group">
    <button ref={trigger} className="group-head settings-window-trigger" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? id : undefined}
      onPointerEnter={(e) => { if (e.pointerType === "mouse") { cancel(); if (!open) timer.current = setTimeout(() => show(), 180); } }}
      onPointerLeave={(e) => { if (e.pointerType === "mouse") leave(); }}
      onClick={() => show(true)} onKeyDown={(e) => { if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); show(true); } }}>
      <span>{title}</span><span className="group-meta">{meta}</span><span aria-hidden>›</span>
    </button>
    {open && createPortal(<div ref={panel} id={id} className="settings-window" role="dialog" aria-label={title} tabIndex={-1}
      style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? "visible" : "hidden" }}
      onPointerEnter={cancel} onPointerLeave={(e) => { if (e.pointerType === "mouse") leave(); }}>
      <div className="view-head"><span className="view-title">{title}</span><button className="close" aria-label={`Close ${title.toLowerCase()}`} onClick={() => close(true)}>×</button></div>
      <div className="settings-window-body">{children}</div>
    </div>, document.body)}
  </section>;
}
