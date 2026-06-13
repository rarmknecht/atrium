import { useMemo, useState } from "react";

import { useModules, useReports } from "../api/hooks";
import { Empty, Markdown, relativeTime } from "../components/common";

export function Reports() {
  const [moduleId, setModuleId] = useState("");
  const [kind, setKind] = useState("");
  const { data: reports } = useReports({
    module_id: moduleId || undefined,
    kind: kind || undefined,
  });
  const { data: modules } = useModules();

  const kinds = useMemo(
    () => Array.from(new Set((reports ?? []).map((r) => r.kind))),
    [reports],
  );

  return (
    <div className="stack">
      <div className="row-between">
        <h1 className="page-title">Reports</h1>
        <div className="row">
          <select className="select" style={{ width: "auto" }} value={moduleId} onChange={(e) => setModuleId(e.target.value)}>
            <option value="">All modules</option>
            {modules?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          <select className="select" style={{ width: "auto" }} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All kinds</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
      </div>

      {reports && reports.length === 0 && <Empty>No reports match.</Empty>}
      <div className="stack">
        {reports?.map((r) => (
          <div key={r.id} className="card">
            <div className="row-between">
              <div className="row">
                <strong>{r.title}</strong>
                <span className="tag">{r.kind}</span>
              </div>
              <div className="row subtle" style={{ fontSize: "var(--text-xs)" }}>
                <span>{r.module_id}</span>
                <span>· {relativeTime(r.created_at)}</span>
              </div>
            </div>
            <hr className="divider" />
            <Markdown>{r.body_md}</Markdown>
          </div>
        ))}
      </div>
    </div>
  );
}
