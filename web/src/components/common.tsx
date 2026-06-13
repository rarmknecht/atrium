import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge status-${status}`}>
      <span className="badge-dot" />
      {status}
    </span>
  );
}

export function Markdown({ children }: { children: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function Toast({ message }: { message: string }) {
  return <div className="toast">{message}</div>;
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const diff = Date.now() - then;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return new Date(then).toLocaleDateString();
}

export function duration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function tokens(inTok: number, outTok: number): string {
  if (!inTok && !outTok) return "—";
  return `${(inTok + outTok).toLocaleString()} tok`;
}
