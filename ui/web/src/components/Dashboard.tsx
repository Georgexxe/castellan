import Link from "next/link";
import {
  shortHash,
  type AuditResponse,
  type CaseOverview,
  type SummaryResponse,
} from "@/lib/api";

type Step = { label: string; value: string; seal?: boolean };

export function Dashboard({
  summary,
  audit,
  cases,
}: {
  summary: SummaryResponse;
  audit: AuditResponse;
  cases: CaseOverview[];
}) {
  const verdict = summary.verdicts[0] ?? "—";
  const remediated = cases.filter((c) => c.proposal_id).length;
  const awaiting = cases.filter((c) => !c.proposal_id);

  const spine: Step[] = [
    { label: "Detect", value: `${summary.findings} findings` },
    { label: "Route", value: "acme-public-data" },
    { label: "Propose", value: "Data Specialist" },
    { label: "Risk", value: verdict },
    { label: "Approve", value: `${summary.approvals} human` },
    { label: "Apply", value: "applied" },
    { label: "Rollback", value: "rolled back" },
    { label: "Audit", value: audit.status, seal: true },
  ];

  return (
    <div className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-8 sm:py-14">
      <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-fg-faint">
        Operations Overview
      </p>
      {/* one decisive end-to-end verdict — read it in three seconds */}
      <div className="mt-2 flex items-center gap-3">
        <span aria-hidden className="inline-block h-2 w-2 rounded-full bg-brass" />
        <h1 className="text-[30px] font-semibold leading-none tracking-tight text-fg">
          End-to-end proof sealed
        </h1>
      </div>
      <p className="mt-3 max-w-2xl text-[13.5px] leading-relaxed text-fg-muted">
        Every remediation is gated, reversible, and cryptographically provable —
        one finding carried from detection to a reversed, audited fix and sealed in
        a tamper-evident chain.
      </p>

      {/* ---- the spine ---- */}
      <section className="mt-8" aria-label="Remediation spine">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch sm:gap-0">
          {spine.map((s, i) => (
            <div key={s.label} className="flex items-stretch sm:flex-1">
              <div
                className={[
                  "flex-1 rounded-sm border px-4 py-3.5",
                  s.seal
                    ? "border-brass/55 bg-brass/8"
                    : "border-ink-600 bg-ink-700",
                ].join(" ")}
              >
                <div className="text-[10px] uppercase tracking-[0.14em] text-fg-faint">
                  {s.label}
                </div>
                {s.seal ? (
                  // the single ceremonial Fraunces moment on the dashboard
                  <div className="mt-1 font-display text-[21px] font-semibold leading-none text-brass-bright">
                    {s.value}
                  </div>
                ) : (
                  <div className="mt-1 text-[14.5px] font-semibold leading-tight text-fg">
                    {s.value}
                  </div>
                )}
              </div>
              {i < spine.length - 1 && (
                <span
                  aria-hidden
                  className="mx-1.5 hidden self-center text-fg-muted sm:inline"
                >
                  →
                </span>
              )}
            </div>
          ))}
        </div>
        <p className="mt-3 text-[12.5px] text-fg-muted">
          Tamper test →{" "}
          <span className="text-vermilion-bright">BREAK at record 4</span>. Run it
          in the{" "}
          <Link
            href="/chain"
            className="text-brass-bright underline-offset-2 hover:underline"
          >
            audit chain
          </Link>
          .
        </p>
      </section>

      {/* ---- proof summary + reserved slot ---- */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <section className="rounded border border-ink-600 bg-ink-700 p-5">
          <div className="flex items-center justify-between">
            <p className="text-[10px] uppercase tracking-[0.18em] text-fg-faint">
              Proof
            </p>
            {summary.reversibility_ok && (
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className="inline-block h-1.5 w-1.5 rounded-full bg-brass"
                />
                <span className="text-[10px] uppercase tracking-[0.12em] text-brass-bright">
                  Reversibility verified
                </span>
              </span>
            )}
          </div>
          <p className="mt-3 text-[13px] text-fg-muted">Audit chain</p>
          <p className="text-[15px] font-semibold text-brass-bright">
            {audit.status} · {audit.length} records sealed
          </p>
          <dl className="mt-3 border-t border-ink-600 pt-3">
            <dt className="text-[10px] uppercase tracking-[0.16em] text-fg-faint">
              Head
            </dt>
            <dd
              className="mt-0.5 break-all font-mono text-[12px] text-fg"
              title={audit.head}
            >
              {shortHash(audit.head, 20, 12)}
            </dd>
          </dl>
          <Link
            href="/chain"
            className="mt-4 inline-block text-[13px] font-medium text-brass-bright underline-offset-2 hover:underline"
          >
            Inspect the chain →
          </Link>
        </section>

        {/* reserved future card — leave the slot, don't build it */}
        <section
          className="flex flex-col rounded border border-dashed border-ink-500 bg-ink-800/40 p-5"
          aria-label="Reserved: Evidence Analyst Summary"
        >
          <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-fg-faint">
            Reserved · Future
          </p>
          <h2 className="mt-2 text-[16px] font-semibold text-fg-muted">
            Evidence Analyst Summary
          </h2>
          <p className="mt-2 text-[12.5px] leading-relaxed text-fg-faint">
            A plain-language read of the case — what was exposed, what was done,
            and why it&apos;s safe — generated from the sealed record. Planned,
            not yet built.
          </p>
          <div className="mt-auto pt-4">
            <span className="inline-block rounded-sm border border-ink-500 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-fg-faint">
              Slot held
            </span>
          </div>
        </section>
      </div>

      {/* ---- cases line ---- */}
      <section className="mt-8" aria-label="Cases">
        <p className="text-[10px] uppercase tracking-[0.18em] text-fg-faint">
          Cases ({summary.cases})
        </p>
        <p className="mt-2 text-[13px] text-fg-muted">
          <span className="text-fg">{remediated} remediated</span> (data:acme-public-data)
          {awaiting.length > 0 && (
            <>
              {" · "}
              {awaiting.length} awaiting specialist (
              {awaiting.map((c) => c.cls).join(", ")})
            </>
          )}
          {" · "}
          <Link
            href="/lifecycle"
            className="text-brass-bright underline-offset-2 hover:underline"
          >
            view lifecycle →
          </Link>
        </p>
      </section>
    </div>
  );
}
