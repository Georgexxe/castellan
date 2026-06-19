import { API_BASE } from "@/lib/api";

export function BridgeOffline({ error }: { error?: string | null }) {
  return (
    <div className="mx-auto max-w-2xl px-5 py-20 sm:px-8">
      <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-vermilion">
        bridge unreachable
      </p>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-fg">
        The read-bridge isn&apos;t answering.
      </h1>
      <p className="mt-3 text-[15px] leading-relaxed text-fg-muted">
        Mission Control reads everything through the FastAPI bridge — it never
        calls Band directly and never mocks data. Start the bridge, then reload.
      </p>
      <pre className="mt-5 overflow-x-auto rounded border border-ink-600 bg-ink-900 p-4 font-mono text-[12.5px] leading-relaxed text-fg">
        <span className="text-fg-faint">cd castellan</span>
        {"\n"}uv run uvicorn ui.api.main:app --reload --port 8000
      </pre>
      <p className="mt-4 font-mono text-[11px] text-fg-faint">
        target: {API_BASE}
        {error ? `  ·  ${error}` : ""}
      </p>
    </div>
  );
}
