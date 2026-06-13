import { useState } from "react";

import type { JsonSchema, JsonSchemaProp } from "../api/types";

/** Renders an editable form from a module ConfigModel's JSON schema.
 * Handles the field shapes pydantic produces: string, number/integer, boolean,
 * enum (string), optional (anyOf with null), and arrays of strings. */
export function SchemaForm({
  schema,
  initial,
  onSubmit,
  saving,
}: {
  schema: JsonSchema;
  initial: Record<string, unknown>;
  onSubmit: (values: Record<string, unknown>) => void;
  saving: boolean;
}) {
  const props = schema.properties ?? {};
  const [values, setValues] = useState<Record<string, unknown>>(() => ({ ...initial }));

  const set = (k: string, v: unknown) => setValues((s) => ({ ...s, [k]: v }));
  const fields = Object.entries(props);

  if (fields.length === 0) {
    return <p className="muted">This module has no configuration.</p>;
  }

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(values);
      }}
    >
      {fields.map(([key, prop]) => (
        <Field key={key} name={key} prop={prop} value={values[key]} onChange={(v) => set(key, v)} />
      ))}
      <div>
        <button className="btn btn-primary" type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save configuration"}
        </button>
      </div>
    </form>
  );
}

function resolveType(prop: JsonSchemaProp): { type: string; enum?: unknown[] } {
  if (prop.enum) return { type: "enum", enum: prop.enum };
  if (prop.anyOf) {
    const real = prop.anyOf.find((p) => p.type && p.type !== "null");
    if (real?.enum) return { type: "enum", enum: real.enum };
    if (real?.type) return { type: Array.isArray(real.type) ? real.type[0] : real.type };
  }
  const t = Array.isArray(prop.type) ? prop.type.find((x) => x !== "null") : prop.type;
  return { type: t ?? "string" };
}

function Field({
  name,
  prop,
  value,
  onChange,
}: {
  name: string;
  prop: JsonSchemaProp;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const { type, enum: choices } = resolveType(prop);
  const label = prop.title ?? name;

  let control: React.ReactNode;
  if (type === "boolean") {
    control = (
      <label className="checkbox-row">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        <span className="muted">{prop.description ?? "Enabled"}</span>
      </label>
    );
  } else if (choices) {
    control = (
      <select className="select" value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        {choices.map((c) => (
          <option key={String(c)} value={String(c)}>
            {String(c)}
          </option>
        ))}
      </select>
    );
  } else if (type === "integer" || type === "number") {
    control = (
      <input
        className="input"
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        min={prop.minimum}
        max={prop.maximum}
        step={type === "integer" ? 1 : "any"}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
      />
    );
  } else if (type === "array") {
    const arr = Array.isArray(value) ? (value as unknown[]) : [];
    control = (
      <input
        className="input"
        value={arr.join(", ")}
        placeholder="comma, separated, values"
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          )
        }
      />
    );
  } else {
    control = (
      <input
        className="input"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <div className="field">
      <label>{label}</label>
      {control}
      {prop.description && type !== "boolean" && <span className="hint">{prop.description}</span>}
    </div>
  );
}
