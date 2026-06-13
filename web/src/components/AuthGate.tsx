import { useEffect, useState } from "react";

import { auth } from "../api/client";

type Phase = "checking" | "need-login" | "ok";

/** Gates the app behind the single-user token when the server requires one.
 * Open (no-auth) servers pass straight through. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");

  const verify = async () => {
    const health = await (await fetch("/api/health")).json();
    if (!health.auth_required) return setPhase("ok");
    // a token is required — probe an authed endpoint with whatever we have
    const res = await fetch("/api/settings", {
      headers: auth.get() ? { Authorization: `Bearer ${auth.get()}` } : {},
    });
    setPhase(res.ok ? "ok" : "need-login");
  };

  useEffect(() => {
    verify().catch(() => setPhase("need-login"));
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    auth.set(input.trim());
    const res = await fetch("/api/settings", {
      headers: { Authorization: `Bearer ${input.trim()}` },
    });
    if (res.ok) {
      setPhase("ok");
    } else {
      auth.clear();
      setError("Invalid token");
    }
  };

  if (phase === "checking") return null;

  if (phase === "need-login") {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <form className="card stack" style={{ width: 340 }} onSubmit={submit}>
          <div className="brand" style={{ padding: 0 }}>
            <span className="brand-dot" /> Atrium
          </div>
          <div className="field">
            <label>Access token</label>
            <input
              className="input"
              type="password"
              autoFocus
              value={input}
              onChange={(e) => setInput(e.target.value)}
            />
            {error && <span className="status-error">{error}</span>}
          </div>
          <button className="btn btn-primary" type="submit">
            Sign in
          </button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
