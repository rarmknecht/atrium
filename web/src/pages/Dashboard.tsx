import { Link } from "react-router-dom";

import { useModules, useRecentRuns, useReports } from "../api/hooks";
import { useRunEvents } from "../api/useRunEvents";
import { Empty, StatusBadge, duration, relativeTime, tokens } from "../components/common";

export function Dashboard() {
  const { data: modules } = useModules();
  const { data: runs } = useRecentRuns();
  const { data: reports } = useReports({});
  const { running } = useRunEvents();

  return (
    <div className="stack">
      <h1 className="page-title">Dashboard</h1>

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
            <p className="muted" style={{ marginTop: 8, marginBottom: 0, fontSize: "var(--text-sm)" }}>
              {m.description ?? "—"}
            </p>
            <div className="row" style={{ marginTop: 12 }}>
              <span className="tag">{m.kind}</span>
            </div>
          </Link>
        ))}
        {modules && modules.length === 0 && (
          <Empty>No modules found. Drop a package into the modules/ directory.</Empty>
        )}
      </div>

      <div className="split" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div className="card">
          <div className="section-label">Recent runs</div>
          {runs && runs.length > 0 ? (
            <table className="table">
              <tbody>
                {runs.slice(0, 10).map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/modules/${r.module_id}`}>{r.module_id}</Link>
                    </td>
                    <td>
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="subtle nowrap">{duration(r.duration_ms)}</td>
                    <td className="subtle nowrap">{tokens(r.tokens_in, r.tokens_out)}</td>
                    <td className="subtle nowrap">{relativeTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No runs yet.</Empty>
          )}
        </div>

        <div className="card">
          <div className="section-label">Recent reports</div>
          {reports && reports.length > 0 ? (
            <div className="stack">
              {reports.slice(0, 8).map((r) => (
                <Link key={r.id} to={`/reports?focus=${r.id}`} className="row-between">
                  <span>{r.title}</span>
                  <span className="subtle nowrap">{relativeTime(r.created_at)}</span>
                </Link>
              ))}
            </div>
          ) : (
            <Empty>No reports yet.</Empty>
          )}
        </div>
      </div>
    </div>
  );
}
