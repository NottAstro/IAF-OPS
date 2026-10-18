import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./OptionPanel.css";

interface Option<T extends string> { value: T; label: string }

/** A small listbox shared by pointer, touch and keyboard; the portal escapes scrolling flyouts. */
export function OptionPanel<T extends string>({ label, value, options, onChange }: {
  label: string; value: T; options: readonly Option<T>[]; onChange: (value: T) => void;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const focusOnOpen = useRef(false);
  const pointerType = useRef("mouse");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const cancel = () => clearTimeout(timer.current);
  const close = (focus = false) => {
    cancel();
    setOpen(false);
    setPosition(null);
    if (focus) trigger.current?.focus();
  };
  const show = (focus = false) => {
    cancel();
    focusOnOpen.current = focus;
    setActive(Math.max(0, options.findIndex((o) => o.value === value)));
    setOpen(true);
    if (focus && open) panel.current?.focus();
  };
  const leave = () => { cancel(); timer.current = setTimeout(() => close(), 200); };
  useEffect(() => () => clearTimeout(timer.current), []);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      if (!trigger.current || !panel.current) return;
      const r = trigger.current.getBoundingClientRect();
      const p = panel.current.getBoundingClientRect();
      const left = r.right + 6 + p.width <= innerWidth - 8 ? r.right + 6 : r.left - p.width - 6;
      setPosition({ left: Math.max(8, Math.min(left, innerWidth - p.width - 8)), top: Math.max(8, Math.min(r.top, innerHeight - p.height - 8)) });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open]);
  useLayoutEffect(() => {
    if (open && position && focusOnOpen.current) {
      panel.current?.focus();
      focusOnOpen.current = false;
    }
  }, [open, position]);
  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => {
      if (e.target instanceof Node && !trigger.current?.contains(e.target) && !panel.current?.contains(e.target)) close();
    };
    const escape = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); } };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("focusin", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("focusin", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const choose = (index: number) => { onChange(options[index].value); close(true); };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault(); setActive(e.key === "Home" ? 0 : options.length - 1);
    } else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(active); }
    else if (e.key === "Tab") close();
  };
  return <>
    <button ref={trigger} type="button" className="option-trigger" aria-label={label} aria-haspopup="listbox"
      aria-expanded={open} aria-controls={open ? id : undefined}
      onPointerEnter={(e) => { if (e.pointerType === "mouse") { cancel(); if (!open) timer.current = setTimeout(() => show(), 180); } }}
      onPointerLeave={(e) => { if (e.pointerType === "mouse") leave(); }}
      onPointerDown={(e) => { pointerType.current = e.pointerType; }}
      onClick={(e) => { if (open && e.detail !== 0 && pointerType.current !== "mouse") close(); else show(true); }}
      onKeyDown={(e) => { if (["Enter", " ", "ArrowDown"].includes(e.key)) { e.preventDefault(); show(true); } }}>
      {options.find((o) => o.value === value)?.label}<span aria-hidden>›</span>
    </button>
    {open && createPortal(<div ref={panel} id={id} className="option-panel" role="listbox" aria-label={label}
      tabIndex={0} aria-activedescendant={`${id}-${active}`} onKeyDown={keys}
      style={{ left: position?.left ?? 0, top: position?.top ?? 0, visibility: position ? "visible" : "hidden" }}
      onPointerEnter={cancel} onPointerLeave={(e) => { if (e.pointerType === "mouse") leave(); }}>
      {options.map((o, i) => <div key={o.value} id={`${id}-${i}`} role="option" aria-selected={o.value === value}
        className={`option-item${active === i ? " active" : ""}`} onPointerMove={() => setActive(i)} onClick={() => choose(i)}>
        <span>{o.label}</span><span aria-hidden>{o.value === value ? "✓" : ""}</span>
      </div>)}
    </div>, document.body)}
  </>;
}
