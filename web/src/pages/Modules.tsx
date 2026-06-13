import { Link } from "react-router-dom";

import { useModules } from "../api/hooks";
import { useRunEvents } from "../api/useRunEvents";
import { Empty, StatusBadge } from "../components/common";

export function Modules() {
  const { data: modules, isLoading } = useModules();
  const { running } = useRunEvents();

  return (
    <div className="stack">
      <h1 className="page-title">Modules</h1>
      {isLoading && <Empty>Loading…</Empty>}
      <div className="grid grid-cards">
        {modules?.map((m) => (
          <Link key={m.id} to={`/modules/${m.id}`} className="card card-hover">
            <div className="row-between">
              <strong>{m.name}</strong>
              {running.has(m.id) ? (
                <span className="badge status-running">
                  <span className="badge-dot" /> running
                </span>
              ) : m.status === "error" ? (
                <StatusBadge status="error" />
              ) : (
                <span className={`badge ${m.enabled ? "status-ready" : "status-disabled"}`}>
                  {m.enabled ? "ready" : "disabled"}
                </span>
              )}
            </div>
            <p className="muted" style={{ marginTop: 8, fontSize: "var(--text-sm)" }}>
              {m.description ?? "—"}
            </p>
            <div className="row wrap" style={{ marginTop: 12 }}>
              <span className="tag">{m.kind}</span>
              <span className="tag mono">v{m.version}</span>
              {m.triggers_supported.map((t) => (
                <span key={t} className="tag">
                  {t}
                </span>
              ))}
            </div>
            {m.status === "error" && (
              <div className="status-error" style={{ marginTop: 8, fontSize: "var(--text-xs)" }}>
                {m.error}
              </div>
            )}
          </Link>
        ))}
      </div>
      {modules && modules.length === 0 && (
        <Empty>No modules found. Drop a package into the modules/ directory and refresh.</Empty>
      )}
    </div>
  );
}
