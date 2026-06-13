import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useDoc, useDocMutations, useTree } from "../api/hooks";
import type { ContextDocSummary, SearchHit } from "../api/types";
import { Empty, Markdown, Toast, relativeTime } from "../components/common";

export function Context() {
  const { data: tree } = useTree();
  const [params, setParams] = useSearchParams();
  const selected = params.get("path");
  const { data: doc } = useDoc(selected);
  const { save, remove, reindex } = useDocMutations();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2500);
  };
  const select = (path: string) => {
    setParams({ path });
    setEditing(false);
  };

  const grouped = useMemo(() => groupByFolder(tree ?? []), [tree]);

  const runSearch = async () => {
    if (!search.trim()) return setHits(null);
    setHits(await api.ask(search, 10));
  };

  const startEdit = () => {
    setDraft(doc?.body ?? "");
    setEditing(true);
  };
  const saveEdit = () => {
    if (!doc) return;
    save.mutate(
      { path: doc.path, frontmatter: doc.frontmatter ?? {}, body: draft },
      { onSuccess: () => { setEditing(false); flash("Saved"); } },
    );
  };
  const createNew = () => {
    const path = prompt("New document path (e.g. notes/idea.md):");
    if (!path) return;
    save.mutate(
      { path, frontmatter: { title: path.split("/").pop()?.replace(".md", "") }, body: "# New document\n\n" },
      { onSuccess: (d) => { select(d.path); flash("Created"); }, onError: (e) => flash(String((e as Error).message)) },
    );
  };

  return (
    <div className="stack">
      <div className="row-between">
        <h1 className="page-title">Context</h1>
        <div className="row">
          <button className="btn btn-sm" onClick={() => reindex.mutate(undefined, { onSuccess: () => flash("Reindexed") })}>
            Reindex
          </button>
          <button className="btn btn-sm btn-primary" onClick={createNew}>
            + New doc
          </button>
        </div>
      </div>

      <div className="row">
        <input
          className="input"
          placeholder="Search the vault…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runSearch()}
        />
        <button className="btn" onClick={runSearch}>
          Search
        </button>
        {hits && (
          <button className="btn btn-ghost btn-sm" onClick={() => { setHits(null); setSearch(""); }}>
            Clear
          </button>
        )}
      </div>

      <div className="split">
        <div className="card card-tight">
          {hits ? (
            <>
              <div className="tree-group">Results</div>
              {hits.length === 0 && <p className="subtle">No matches.</p>}
              {hits.map((h) => (
                <div
                  key={h.doc.path}
                  className={`tree-item${selected === h.doc.path ? " active" : ""}`}
                  onClick={() => select(h.doc.path)}
                >
                  {h.doc.title}
                  <div className="subtle" style={{ fontSize: "var(--text-xs)" }}>
                    {h.doc.path}
                  </div>
                </div>
              ))}
            </>
          ) : (
            Object.entries(grouped).map(([folder, docs]) => (
              <div key={folder}>
                <div className="tree-group">{folder}</div>
                {docs.map((d) => (
                  <div
                    key={d.path}
                    className={`tree-item${selected === d.path ? " active" : ""}`}
                    onClick={() => select(d.path)}
                  >
                    {d.title}
                  </div>
                ))}
              </div>
            ))
          )}
          {tree && tree.length === 0 && <Empty>Empty vault.</Empty>}
        </div>

        <div className="card">
          {!doc ? (
            <Empty>Select a document, or create one.</Empty>
          ) : (
            <div className="stack">
              <div className="row-between">
                <div>
                  <h2>{doc.title}</h2>
                  <div className="row wrap" style={{ marginTop: 6 }}>
                    <span className="mono subtle">{doc.path}</span>
                    {doc.tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="row">
                  {editing ? (
                    <>
                      <button className="btn btn-sm" onClick={() => setEditing(false)}>
                        Cancel
                      </button>
                      <button className="btn btn-sm btn-primary" onClick={saveEdit} disabled={save.isPending}>
                        Save
                      </button>
                    </>
                  ) : (
                    <>
                      <button className="btn btn-sm" onClick={startEdit}>
                        Edit
                      </button>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() =>
                          confirm(`Delete ${doc.path}?`) &&
                          remove.mutate(doc.path, { onSuccess: () => { setParams({}); flash("Deleted"); } })
                        }
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
              <hr className="divider" />
              {editing ? (
                <textarea className="textarea mono" style={{ minHeight: 380 }} value={draft} onChange={(e) => setDraft(e.target.value)} />
              ) : (
                <Markdown>{doc.body ?? ""}</Markdown>
              )}

              {(doc.links.length > 0 || doc.backlinks.length > 0) && !editing && (
                <>
                  <hr className="divider" />
                  <div className="split" style={{ gridTemplateColumns: "1fr 1fr" }}>
                    <div>
                      <div className="section-label">Links out</div>
                      {doc.links.length === 0 && <span className="subtle">none</span>}
                      {doc.links.map((l, i) => (
                        <div key={i} className="row" style={{ fontSize: "var(--text-sm)" }}>
                          {l.relation && <span className="tag">{l.relation}</span>}
                          {l.resolved ? (
                            <a onClick={() => select(l.target)} style={{ cursor: "pointer" }}>
                              {l.target}
                            </a>
                          ) : (
                            <span className="status-error">{l.target} (dead)</span>
                          )}
                        </div>
                      ))}
                    </div>
                    <div>
                      <div className="section-label">Backlinks</div>
                      {doc.backlinks.length === 0 && <span className="subtle">none</span>}
                      {doc.backlinks.map((b) => (
                        <div key={b} style={{ fontSize: "var(--text-sm)" }}>
                          <a onClick={() => select(b)} style={{ cursor: "pointer" }}>
                            {b}
                          </a>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}
              {doc.updated && !editing && (
                <div className="subtle" style={{ fontSize: "var(--text-xs)" }}>
                  updated {relativeTime(doc.updated)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      {toast && <Toast message={toast} />}
    </div>
  );
}

function groupByFolder(docs: ContextDocSummary[]): Record<string, ContextDocSummary[]> {
  const out: Record<string, ContextDocSummary[]> = {};
  for (const d of docs) {
    const folder = d.path.includes("/") ? d.path.split("/")[0] : "root";
    (out[folder] ??= []).push(d);
  }
  return out;
}
