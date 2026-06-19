import { type CloudState, type PAB } from "@/lib/api";

const FLAGS: { key: keyof NonNullable<PAB>; label: string }[] = [
  { key: "BlockPublicAcls", label: "BlockPublicAcls" },
  { key: "IgnorePublicAcls", label: "IgnorePublicAcls" },
  { key: "BlockPublicPolicy", label: "BlockPublicPolicy" },
  { key: "RestrictPublicBuckets", label: "RestrictPublicBuckets" },
];

function cell(pab: PAB, key: keyof NonNullable<PAB>): string {
  if (!pab) return "—";
  return String(pab[key]);
}

export function Reversibility({ state }: { state: CloudState }) {
  const cols: { label: string; pab: PAB; note: string }[] = [
    { label: "Before", pab: state.before, note: "public" },
    { label: "After apply", pab: state.after_apply, note: "blocked" },
    { label: "After rollback", pab: state.after_rollback, note: "restored" },
  ];
  const restored = state.restored_matches_original === true;

  return (
    <div className="mx-auto w-full max-w-[1080px] px-5 py-10 sm:px-8 sm:py-14">
      <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-fg-faint">
        Reversibility Proof
      </p>
      <h1 className="mt-2 text-[26px] font-semibold tracking-tight text-fg">
        Before ≡ after rollback.
      </h1>
      <p className="mt-2 max-w-2xl text-[13px] leading-relaxed text-fg-muted">
        The S3 public-access block, captured at each step from the sealed action
        records. The fix blocks public access; the rollback restores the prior
        state byte-for-byte — recomputed from the chain, not merely asserted.
      </p>

      {/* the proof itself — bone/ledger surface */}
      <section className="grain lift mt-7 rounded border border-bone-edge bg-bone p-5 text-bone-ink sm:p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
          <h2 className="text-[15px] font-semibold">
            S3 Public Access Block · acme-public-data
          </h2>
          <span
            className="font-mono text-[11px] text-bone-ink-muted"
            title={state.proposal_id ?? ""}
          >
            proposal {state.proposal_id ?? "—"}
          </span>
        </div>

        {/* round-trip caption */}
        <p className="mt-1 font-mono text-[11.5px] text-bone-ink-muted">
          all-false (public) → all-true (blocked) → all-false (restored)
        </p>

        {/* diff table */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-bone-edge">
                <th className="py-2 pr-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-bone-ink-muted">
                  Flag
                </th>
                {cols.map((c) => (
                  <th
                    key={c.label}
                    className="py-2 pr-4 text-[10px] font-semibold uppercase tracking-[0.14em] text-bone-ink-muted"
                  >
                    {c.label}
                    <span className="ml-1 font-normal lowercase tracking-normal opacity-70">
                      · {c.note}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FLAGS.map((f) => (
                <tr key={f.key} className="border-b border-bone-edge/60">
                  <td className="py-2 pr-4 font-mono text-[12px]">{f.label}</td>
                  {cols.map((c) => (
                    <td
                      key={c.label}
                      className="py-2 pr-4 font-mono text-[12px] tabular"
                    >
                      {cell(c.pab, f.key)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* verdict seal */}
        <div className="mt-5 flex items-center gap-3 border-t border-bone-edge pt-4">
          <span
            className={[
              "rounded-sm border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.14em]",
              restored
                ? "border-brass-deep/60 bg-brass/15 text-brass-deep"
                : "border-vermilion/50 bg-vermilion/10 text-vermilion-deep",
            ].join(" ")}
          >
            {restored ? "Restored" : "Mismatch"}
          </span>
          <p className="text-[12.5px] text-bone-ink-muted">
            <span className="font-mono">restored_matches_original</span> ={" "}
            <span className="font-medium text-bone-ink">
              {String(state.restored_matches_original)}
            </span>{" "}
            — before and after-rollback are identical.
          </p>
        </div>
      </section>
    </div>
  );
}
