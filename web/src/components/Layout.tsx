import { NavLink, Outlet } from "react-router-dom";

import { useRunEvents } from "../api/useRunEvents";
import { useTheme } from "../theme/ThemeProvider";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/modules", label: "Modules" },
  { to: "/context", label: "Context" },
  { to: "/reports", label: "Reports" },
  { to: "/settings", label: "Settings" },
];

export function Layout() {
  const { theme, toggle } = useTheme();
  const { connected, running } = useRunEvents();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-dot" />
          Atrium
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
          >
            {n.label}
          </NavLink>
        ))}
        <div className="grow" />
        <div className="row subtle" style={{ fontSize: "var(--text-xs)", padding: "0 12px" }}>
          <span
            className="badge-dot"
            style={{ background: connected ? "var(--ok)" : "var(--text-subtle)" }}
          />
          {connected ? "live" : "offline"}
          {running.size > 0 && <span>· {running.size} running</span>}
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div />
          <button className="icon-btn" onClick={toggle} title="Toggle theme">
            {theme === "dark" ? "☾" : "☀"}
          </button>
        </header>
        <div className="content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
