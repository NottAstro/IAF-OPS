import { useEffect, useState } from "react";

/** Opening shutter: IAF crest centred, then the two halves slide apart onto the login / map. Click to skip. */
export function Splash() {
  const [phase, setPhase] = useState<"hold" | "open" | "gone">("hold");
  useEffect(() => {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const open = setTimeout(() => setPhase("open"), reduce ? 600 : 2000);
    return () => clearTimeout(open);
  }, []);
  useEffect(() => {
    if (phase !== "open") return;
    const t = setTimeout(() => setPhase("gone"), 950);
    return () => clearTimeout(t);
  }, [phase]);
  if (phase === "gone") return null;
  return (
    <div className={`splash${phase === "open" ? " open" : ""}`} onClick={() => setPhase("open")} role="presentation">
      <div className="shutter shutter-l" />
      <div className="shutter shutter-r" />
      <div className="splash-core">
        <div className="crest-ring"><img src="/iaf-crest.svg" alt="Indian Air Force crest" /></div>
        <div className="splash-title">AIR OPERATIONS PICTURE</div>
        <div className="splash-sub">SIH26250 · PHASE 1 PROTOTYPE</div>
        <div className="splash-bar" />
      </div>
    </div>
  );
}
