import { useSettings } from "../api/hooks";
import { Empty } from "../components/common";

export function Settings() {
  const { data: s } = useSettings();
  if (!s) return <Empty>Loading…</Empty>;

  const rows: [string, React.ReactNode][] = [
    ["Version", s.version],
    ["Schema version", `v${s.schema_version}`],
    ["Vault path", <span className="mono">{s.vault_path}</span>],
    ["Modules path", <span className="mono">{s.modules_path}</span>],
    ["Indexed documents", s.doc_count],
    ["Vault file watching", <Bool v={s.watch_vault} yes="on" no="off" />],
    [
      "Embeddings",
      s.embeddings_active ? (
        <span className="mono">
          {s.embeddings_provider} · {s.embedding_model}
        </span>
      ) : (
        <span className="status-disabled">disabled (BM25-only search)</span>
      ),
    ],
    ["LLM model", <span className="mono">{s.llm_model}</span>],
    ["Librarian router model", <span className="mono">{s.router_model}</span>],
    [
      "Anthropic API key",
      <Bool v={s.anthropic_configured} yes="configured" no="not set — agent modules disabled" />,
    ],
  ];

  return (
    <div className="stack">
      <h1 className="page-title">Settings</h1>
      <p className="muted">
        These are read from the server environment / <span className="mono">.env</span>. Edit them
        there and restart Atrium.
      </p>
      <div className="card">
        <table className="table">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td className="subtle" style={{ width: 220 }}>
                  {k}
                </td>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Bool({ v, yes, no }: { v: boolean; yes: string; no: string }) {
  return <span className={v ? "status-ready" : "status-disabled"}>{v ? yes : no}</span>;
}
