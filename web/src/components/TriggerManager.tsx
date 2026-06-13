import { useState } from "react";

import type { ModuleDetail, Trigger, TriggerType } from "../api/types";
import { useTriggerMutations, useTriggers } from "../api/hooks";
import { relativeTime } from "./common";

export function TriggerManager({ module }: { module: ModuleDetail }) {
  const { data: triggers } = useTriggers(module.id);
  const { create, update, remove } = useTriggerMutations(module.id);
  const [adding, setAdding] = useState<TriggerType | "">("");

  const addable = module.triggers_supported.filter((t) => t !== "manual");

  return (
    <div className="stack">
      <div className="row-between">
        <div className="section-label" style={{ margin: 0 }}>
          Triggers
        </div>
        <div className="row">
          <select
            className="select"
            style={{ width: "auto" }}
            value={adding}
            onChange={(e) => setAdding(e.target.value as TriggerType)}
          >
            <option value="">Add trigger…</option>
            {addable.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          {adding && (
            <NewTrigger
              type={adding}
              onCreate={(config) =>
                create.mutate(
                  { module_id: module.id, type: adding, config },
                  { onSuccess: () => setAdding("") },
                )
              }
              error={create.isError ? String((create.error as Error).message) : undefined}
            />
          )}
        </div>
      </div>

      {triggers && triggers.length === 0 && (
        <p className="muted">No triggers yet. Add a schedule, continuous loop, or webhook above.</p>
      )}
      <div className="stack">
        {triggers?.map((t) => (
          <TriggerRow
            key={t.id}
            trigger={t}
            onToggle={(enabled) => update.mutate({ id: t.id, body: { enabled } })}
            onDelete={() => remove.mutate(t.id)}
          />
        ))}
      </div>
    </div>
  );
}

function NewTrigger({
  type,
  onCreate,
  error,
}: {
  type: TriggerType;
  onCreate: (config: Record<string, unknown>) => void;
  error?: string;
}) {
  const [cron, setCron] = useState("0 7 * * *");
  const [interval, setInterval] = useState(300);
  const [sleep, setSleep] = useState(60);
  const [mode, setMode] = useState<"cron" | "interval">("cron");

  const submit = () => {
    if (type === "schedule")
      onCreate(mode === "cron" ? { cron } : { interval_seconds: interval });
    else if (type === "continuous") onCreate({ sleep_seconds: sleep });
    else onCreate({});
  };

  return (
    <div className="row">
      {type === "schedule" && (
        <>
          <select
            className="select"
            style={{ width: "auto" }}
            value={mode}
            onChange={(e) => setMode(e.target.value as "cron" | "interval")}
          >
            <option value="cron">cron</option>
            <option value="interval">interval</option>
          </select>
          {mode === "cron" ? (
            <input className="input mono" style={{ width: 150 }} value={cron} onChange={(e) => setCron(e.target.value)} />
          ) : (
            <input
              className="input"
              type="number"
              style={{ width: 100 }}
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
            />
          )}
        </>
      )}
      {type === "continuous" && (
        <input
          className="input"
          type="number"
          style={{ width: 110 }}
          value={sleep}
          onChange={(e) => setSleep(Number(e.target.value))}
          title="sleep seconds between runs"
        />
      )}
      <button className="btn btn-sm btn-primary" onClick={submit}>
        Create
      </button>
      {error && <span className="status-error">{error}</span>}
    </div>
  );
}

function TriggerRow({
  trigger,
  onToggle,
  onDelete,
}: {
  trigger: Trigger;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const webhookUrl =
    trigger.type === "webhook" && trigger.token
      ? `${location.origin}/api/hooks/${trigger.module_id}/${trigger.token}`
      : null;

  return (
    <div className="card card-tight">
      <div className="row-between">
        <div className="row">
          <span className="badge">{trigger.type}</span>
          <span className="mono subtle">{describeConfig(trigger)}</span>
        </div>
        <div className="row">
          {trigger.live.registered ? (
            <span className="badge status-ok">
              <span className="badge-dot" /> live
            </span>
          ) : (
            <span className="badge status-disabled">paused</span>
          )}
          <button className="btn btn-sm" onClick={() => onToggle(!trigger.enabled)}>
            {trigger.enabled ? "Pause" : "Resume"}
          </button>
          <button className="btn btn-sm btn-danger" onClick={onDelete}>
            Delete
          </button>
        </div>
      </div>
      {trigger.live.next_fire_time && (
        <div className="subtle" style={{ marginTop: 8, fontSize: "var(--text-xs)" }}>
          next fire {relativeTime(trigger.live.next_fire_time)}
        </div>
      )}
      {webhookUrl && (
        <div className="logs" style={{ marginTop: 8, maxHeight: "none" }}>
          {webhookUrl}
        </div>
      )}
    </div>
  );
}

function describeConfig(t: Trigger): string {
  if (t.type === "schedule")
    return t.config.cron ? `cron: ${t.config.cron}` : `every ${t.config.interval_seconds}s`;
  if (t.type === "continuous") return `every ${t.config.sleep_seconds}s`;
  if (t.type === "webhook") return "POST endpoint";
  return "";
}
