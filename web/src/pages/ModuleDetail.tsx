import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useModule, useRunModule, useRuns, useSaveConfig, useSetEnabled } from "../api/hooks";
import type { Run } from "../api/types";
import { useRunEvents } from "../api/useRunEvents";
import { SchemaForm } from "../components/SchemaForm";
import { TriggerManager } from "../components/TriggerManager";
import { Empty, Spinner, StatusBadge, Toast, duration, relativeTime, tokens } from "../components/common";

export function ModuleDetail() {
  const { id = "" } = useParams();
  const { data: module, isLoading } = useModule(id);
  const { data: runs } = useRuns(id);
  const runMutation = useRunModule(id);
  const saveConfig = useSaveConfig(id);
  const setEnabled = useSetEnabled(id);
  const { running } = useRunEvents();
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  if (isLoading || !module) return <Empty>Loading…</Empty>;
  const isRunning = running.has(id);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2500);
  };

  return (
    <div className="stack">
      <div className="row-between">
        <div>
          <Link to="/modules" className="subtle">
            ← Modules
          </Link>
          <h1 className="page-title" style={{ marginTop: 4 }}>
            {module.name}
          </h1>
          <p className="muted">{module.description}</p>
        </div>
        <div className="row">
          <button className="btn" onClick={() => setEnabled.mutate(!module.enabled)}>
            {module.enabled ? "Disable" : "Enable"}
          </button>
          <button
            className="btn btn-primary"
            disabled={module.status !== "ready" || runMutation.isPending || isRunning}
            onClick={() =>
              runMutation.mutate(undefined, {
                onSuccess: (r) => flash(`Run ${r.status}: ${r.summary}`),
              })
            }
          >
            {runMutation.isPending || isRunning ? <Spinner /> : "▶"} Run now
          </button>
        </div>
      </div>

      {module.status === "error" && (
        <div className="card status-error">Module failed to load: {module.error}</div>
      )}

      <div className="split" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)" }}>
        <div className="card">
          <div className="section-label">Configuration</div>
          {module.config_schema && (
            <SchemaForm
              schema={module.config_schema}
              initial={module.config ?? {}}
              saving={saveConfig.isPending}
              onSubmit={(values) =>
                saveConfig.mutate(values, {
                  onSuccess: () => flash("Configuration saved"),
                  onError: (e) => flash(String((e as Error).message)),
                })
              }
            />
          )}
        </div>

        <div className="card">
          <TriggerManager module={module} />
        </div>
      </div>

      <div className="card">
        <div className="section-label">Run history</div>
        {runs && runs.length > 0 ? (
          <table className="table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Trigger</th>
                <th>Summary</th>
                <th>Duration</th>
                <th>Tokens</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="row-click" onClick={() => setSelectedRun(r)}>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="subtle">{r.trigger_type}</td>
                  <td>{r.summary || "—"}</td>
                  <td className="subtle nowrap">{duration(r.duration_ms)}</td>
                  <td className="subtle nowrap">{tokens(r.tokens_in, r.tokens_out)}</td>
                  <td className="subtle nowrap">{relativeTime(r.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>No runs yet — hit “Run now”.</Empty>
        )}
      </div>

      {selectedRun && (
        <div className="card">
          <div className="row-between">
            <div className="section-label" style={{ margin: 0 }}>
              Run logs · {selectedRun.summary}
            </div>
            <button className="btn btn-sm btn-ghost" onClick={() => setSelectedRun(null)}>
              Close
            </button>
          </div>
          <pre className="logs" style={{ marginTop: 12 }}>
            {selectedRun.logs || "(no logs)"}
          </pre>
        </div>
      )}

      {toast && <Toast message={toast} />}
    </div>
  );
}
