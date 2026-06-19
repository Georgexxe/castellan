import { type AuditRecord, type CaseDetail } from "@/lib/api";

// Narrative labels for the lifecycle (calmer than the chain's record-type labels).
const STEP_LABEL: Record<string, string> = {
  case_open: "Scanner finding — case opened",
  contribution: "Data Specialist proposal",
  constraint: "Risk verdict",
  human_approval: "Human approval",
  action_applied: "Action applied",
  human_rollback: "Human rollback",
  action_rolled_back: "Action rolled back",
};

function when(inserted: string): string {
  // deterministic, no Date(): "2026-06-19 10:26:21" from "2026-06-19 10:26:21.983044+00:00"
  return inserted.replace("T", " ").slice(0, 19) + " UTC";
}

function statusOf(rec: AuditRecord): { text: string; tone: "brass" | "muted" } {
  switch (rec.record_type) {
    case "constraint": {
      const v = String(rec.payload?.verdict ?? "");
      return v === "reject"
        ? { text: "rejected", tone: "muted" }
        : { text: "approved", tone: "brass" };
    }
    case "contribution":
      return { text: "proposed", tone: "brass" };
    case "human_approval":
      return { text: "approved", tone: "brass" };
    case "action_applied":
      return { text: "applied", tone: "brass" };
    case "human_rollback":
      return { text: "authorized", tone: "brass" };
    case "action_rolled_back":
      return { text: "rolled back", tone: "brass" };
    default:
      return { text: "sealed", tone: "brass" };
  }
}

export function Lifecycle({ detail }: { detail: CaseDetail }) {
  return (
    <div className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-8 sm:py-14">
      <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-fg-faint">
        Case Lifecycle
      </p>
      <h1 className="mt-2 text-[26px] font-semibold tracking-tight text-fg">
        {detail.case_key ?? detail.case_id}
      </h1>
      <p className="mt-2 text-[13px] text-fg-muted">
        The full typed sequence for one case, in order — from detection to a
        reversed, audited remediation. Each step expands to its raw sealed record.
      </p>

      <ol className="mt-8" role="list">
        {detail.records.map((rec, i) => {
          const isHuman = (rec.sender_type ?? "").toLowerCase() === "user";
          const isLast = i === detail.records.length - 1;
          const status = statusOf(rec);
          return (
            <li key={rec.seq} className="grid grid-cols-[2rem_1fr] gap-x-3">
              {/* marker + connector */}
              <div className="flex flex-col items-center">
                <div className="tabular flex h-7 w-7 items-center justify-center rounded-sm border border-ink-500 bg-ink-700 font-mono text-[12px] text-fg">
                  {i + 1}
                </div>
                {!isLast && <div className="w-px flex-1 bg-ink-500" aria-hidden />}
              </div>

              {/* step card (ink — quiet) */}
              <div className="mb-4 rounded border border-ink-600 bg-ink-700 p-4">
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                  <div className="min-w-0">
                    <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-fg-faint">
                      {rec.record_type}
                    </p>
                    <h3 className="mt-0.5 text-[15px] font-semibold leading-tight text-fg">
                      {STEP_LABEL[rec.record_type] ?? rec.record_type}
                    </h3>
                    <p className="mt-1 text-[12.5px] text-fg-muted">
                      <span className="font-medium text-fg">
                        {rec.sender_name ?? "—"}
                      </span>
                      <span className="ml-2 rounded-sm border border-ink-500 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-fg-faint">
                        {isHuman ? "human" : "agent"}
                      </span>
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="flex items-center justify-end gap-1.5 text-[12px] font-semibold">
                      <span
                        aria-hidden
                        className={`inline-block h-1.5 w-1.5 rounded-full ${
                          status.tone === "brass" ? "bg-brass" : "bg-fg-faint"
                        }`}
                      />
                      <span
                        className={
                          status.tone === "brass"
                            ? "text-brass-bright"
                            : "text-fg-muted"
                        }
                      >
                        {status.text}
                      </span>
                    </p>
                    <p className="mt-0.5 font-mono text-[11px] text-fg-faint">
                      {when(rec.inserted_at)}
                    </p>
                  </div>
                </div>

                <details className="group mt-3 border-t border-ink-600 pt-2">
                  <summary className="cursor-pointer list-none text-[11px] uppercase tracking-[0.12em] text-fg-muted transition-colors hover:text-fg">
                    <span className="group-open:hidden">▸ View record JSON</span>
                    <span className="hidden group-open:inline">▾ Hide record JSON</span>
                  </summary>
                  {/* raw sealed record = proof → bone surface */}
                  <pre className="grain lift mt-3 max-h-80 overflow-auto rounded border border-bone-edge bg-bone p-3 font-mono text-[11.5px] leading-relaxed text-bone-ink">
                    {JSON.stringify(rec.payload, null, 2)}
                  </pre>
                </details>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
