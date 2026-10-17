import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import { useLiveSocket } from "../api/ws";
import { MapBoundary } from "../components/MapBoundary";
import { Splash } from "../components/Splash";
import { Toasts } from "../components/ui";
import { MapScreen } from "../features/MapScreen";
import { istTime, label, zulu } from "../lib/format";
import { MapView } from "../map/MapView";
import { Admin } from "../pages/Admin";
import { Alerts, Audit } from "../pages/Alerts";
import { Inventory } from "../pages/Inventory";
import { Overview } from "../pages/Overview";
import { PilotProfile, Pilots } from "../pages/Pilots";

export function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me"), retry: false, staleTime: Infinity });
  useEffect(() => {
    const out = () => qc.setQueryData(["me"], null);
    addEventListener("airops:unauthorised", out);
    return () => removeEventListener("airops:unauthorised", out);
  }, [qc]);
  const user = me.data ?? null;
  useLiveSocket(!!user);
  return (
    <>
      <Splash />
      {!me.isLoading && (
        <div className="shell">
          {user ? <TopBar user={user} /> : <div className="topbar"><Brand /></div>}
          <main className="main">{user ? <Authed user={user} /> : <Login />}</main>
          <Toasts />
        </div>
      )}
    </>
  );
}

function Authed({ user }: { user: User }) {
  const loc = useLocation();
  const onMap = loc.pathname === "/map" || loc.pathname === "/";
  return (
    <>
      <div className="map-wrap" aria-hidden={!onMap}><MapBoundary><MapView hidden={!onMap} /></MapBoundary></div>
      <div className="map-wrap" style={{ pointerEvents: onMap ? "none" : "auto", background: onMap ? "transparent" : "var(--bg)", zIndex: onMap ? 2 : 10 }}>
        <div style={{ pointerEvents: "auto", height: onMap ? undefined : "100%" }}>
          <Routes>
            <Route path="/" element={<Navigate to="/map" replace />} />
            <Route path="/map" element={<MapScreen user={user} />} />
            <Route path="/overview" element={<Overview />} />
            <Route path="/inventory" element={<Navigate to="/inventory/aircraft" replace />} />
            <Route path="/inventory/:entity/:typeId?" element={<Inventory user={user} />} />
            <Route path="/pilots" element={<Pilots user={user} />} />
            <Route path="/pilots/:id" element={<PilotProfile user={user} />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/audit" element={user.role === "VIEWER" ? <Navigate to="/map" /> : <Audit user={user} />} />
            <Route path="/admin" element={user.role === "ADMIN" ? <Admin /> : <Navigate to="/map" />} />
            <Route path="*" element={<Navigate to="/map" />} />
          </Routes>
        </div>
      </div>
    </>
  );
}

function Brand() {
  return (
    <span className="brand">
      <img src="/iaf-crest.svg" alt="" />
      <span>Air Operations Picture<span className="brand-sub">SIH26250 · Phase 1 prototype</span></span>
    </span>
  );
}

function TopBar({ user }: { user: User }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const alerts = useQuery({ queryKey: ["alerts", "counts"], queryFn: () => api<{ open_counts: Record<string, number> }>("/alerts?limit=1"), refetchInterval: 20000 });
  const crit = alerts.data?.open_counts.CRITICAL ?? 0;
  const warn = alerts.data?.open_counts.WARNING ?? 0;
  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
    qc.setQueryData(["me"], null);
    nav("/map");
  };
  const link = (to: string, text: string) => <NavLink to={to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>{text}</NavLink>;
  return (
    <header className="topbar">
      <Brand />
      <nav className="nav" aria-label="Main">
        {link("/map", "Map")}{link("/overview", "Overview")}{link("/inventory", "Inventory")}{link("/pilots", "Aircrew")}
        <NavLink to="/alerts" className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
          Alerts{crit + warn > 0 && <span className="badge-count" style={{ background: crit ? "var(--critical)" : "var(--warning)" }} aria-label={`${crit} critical, ${warn} warning`}>{crit ? `■ ${crit}` : `◆ ${warn}`}</span>}
        </NavLink>
        {user.role !== "VIEWER" && link("/audit", "Audit")}
        {user.role === "ADMIN" && link("/admin", "Admin")}
      </nav>
      <span className="topbar-spacer" />
      <div className="clock" title="Real time"><span className="clock-main">{istTime(now).replace(" IST", "")} IST</span><span className="clock-sub">{zulu(now)}</span></div>
      <div className="user-chip">
        <span>{user.display_name}</span>
        <span className="muted">{label(user.role)}{user.base_code ? ` · ${user.base_code}` : user.command_code ? ` · ${user.command_code}` : ""}</span>
      </div>
      <button className="btn btn-ghost btn-sm" onClick={logout}>Sign out</button>
    </header>
  );
}

function Login() {
  const qc = useQueryClient();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr("");
    try {
      const me = await api<User>("/auth/login", { method: "POST", body: { username: u, password: p } });
      qc.setQueryData(["me"], me);
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login">
      <form className="login-box" onSubmit={submit}>
        <img className="login-crest" src="/iaf-crest.svg" alt="Indian Air Force crest" />
        <div className="login-title">Air Operations Picture</div>
        <div className="login-sub">Inventory and common operating picture · SIH26250</div>
        <label className="field"><span className="field-label">Username</span>
          <input className="input" autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} /></label>
        <label className="field" style={{ marginTop: 12 }}><span className="field-label">Password</span>
          <input className="input" type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        {err && <div className="error-text" style={{ marginTop: 8 }}>■ {err}</div>}
        <button className="btn btn-primary" style={{ marginTop: 16, width: "100%" }} disabled={busy || !u || !p}>{busy ? "Signing in…" : "Sign in"}</button>
        <div className="disclaimer">
          All operational data in this system is simulated for SIH 2026. Base locations are from public sources. No real personnel are shown.
        </div>
        <div className="dim" style={{ fontSize: 12, marginTop: 12 }}>Demo users: admin, airhq, wac.hq, eac.hq, cdr.viax, cdr.vetz, cdr.vijo, viewer</div>
      </form>
    </div>
  );
}
