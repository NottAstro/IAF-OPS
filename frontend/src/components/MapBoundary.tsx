import { Component, type ReactNode } from "react";

/** Keeps every non-map screen usable when the map can't start (e.g. no WebGL). */
export class MapBoundary extends Component<{ children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(e: unknown) {
    return { error: e instanceof Error ? e.message : String(e) };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page" style={{ display: "grid", placeItems: "center" }}>
        <div className="notice" style={{ maxWidth: 620, lineHeight: "22px" }}>
          <strong style={{ color: "var(--text-1)" }}>The map couldn't start: this browser refused to create a WebGL context.</strong>
          <ol style={{ margin: "8px 0", paddingLeft: 20 }}>
            <li>Chrome: Settings → System → turn on <b>Use graphics acceleration when available</b>, then relaunch.</li>
            <li>Quit the browser completely (⌘Q) and reopen it. A crashed GPU process disables WebGL until a full restart.</li>
            <li>Close other map-heavy tabs (e.g. God's Eye View): browsers allow only a limited number of WebGL contexts.</li>
            <li>Check <span className="mono">chrome://gpu</span>: "WebGL" should say <i>Hardware accelerated</i>. Or try Safari.</li>
          </ol>
          Overview, Inventory, Aircrew and Alerts still work.
          <div className="mono dim" style={{ marginTop: 8, fontSize: 11 }}>{this.state.error.split("\n")[0].slice(0, 200)}</div>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => location.reload()}>Try again</button>
        </div>
      </div>
    );
  }
}
