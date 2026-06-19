"use client";

import { useState, type CSSProperties } from "react";
import {
  getTamper,
  RECORD_LABEL,
  shortHash,
  type AuditResponse,
  type AuditRecord,
  type TamperResponse,
} from "@/lib/api";

type Status = "valid" | "broken";

const STAGGER_MS = 70;

export function AuditChain({ data }: { data: AuditResponse }) {
  const [status, setStatus] = useState<Status>(
    data.status === "VALID" ? "valid" : "broken",
  );
  const [tamper, setTamper] = useState<TamperResponse | null>(null);
  const [brokenFrom, setBrokenFrom] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const broken = status === "broken";

  async function runTamper() {
    setLoading(true);
    setErr(null);
    try {
      const t = await getTamper(data.room_id);
      setTamper(t);
      setBrokenFrom(t.first_broken_seq ?? 0);
      setStatus("broken");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "tamper request failed");
    } finally {
      setLoading(false);
    }
  }

  function reseal() {
    setStatus("valid");
    setBrokenFrom(null);
    setTamper(null);
  }

  const headHash = broken && tamper ? tamper.tampered_head : data.head;

  return (
    <div className="mx-auto w-full max-w-3xl px-5 py-10 sm:px-8 sm:py-14">
      {/* ---- thesis: grasp the screen in three seconds ---- */}
      <p className="mb-5 max-w-xl text-[13.5px] leading-relaxed text-fg-muted">
        Every remediation is gated, reversible, and cryptographically provable.
      </p>

      {/* ---- ceremonial verdict ---- */}
      <VerdictPanel
        status={status}
        headHash={headHash}
        anchor={data.anchor}
        reversibilityOk={data.reversibility_ok}
        tamper={tamper}
      />

      {/* ---- controls ---- */}
      <div className="mt-5 flex flex-wrap items-center gap-3">
        {!broken ? (
          <button
            type="button"
            onClick={runTamper}
            disabled={loading}
            className="rounded-sm border border-brass/60 bg-brass/8 px-5 py-2.5 text-[14px] font-semibold text-fg transition-colors hover:bg-brass/16 hover:text-brass-bright disabled:opacity-50"
          >
            {loading ? "Running tamper test…" : "Run tamper test"}
          </button>
        ) : (
          <button
            type="button"
            onClick={reseal}
            className="rounded-sm border border-brass/55 bg-brass/10 px-4 py-2 text-[13px] font-semibold text-brass-bright transition-colors hover:bg-brass/18"
          >
            Re-seal chain
          </button>
        )}
        <p className="max-w-md text-[12.5px] leading-snug text-fg-muted">
          {broken
            ? "One record was mutated in memory. Every record after it is invalidated — the head no longer matches the anchor."
            : "Mutate one record in memory and watch the hash chain break downstream. Nothing on the server changes."}
        </p>
      </div>
      {err && (
        <p className="mt-2 font-mono text-[12px] text-vermilion">{err}</p>
      )}

      {/* ---- chain title (ceremonial) ---- */}
      <div className="mt-12">
        <h1 className="font-display text-[30px] font-semibold leading-none tracking-tight text-fg">
          Audit Chain
        </h1>
        <p className="mt-2 text-[13px] text-fg-muted">
          {`SHA-256 hash chain · ${data.length} sealed records reconstructed from the Band room. Each block's hash folds in the one before it.`}
        </p>
      </div>

      {/* ---- the chain ---- */}
      <ol className="mt-7" role="list">
        {data.records.map((rec, i) => (
          <ChainItem
            key={rec.seq}
            rec={rec}
            index={i}
            isFirst={i === 0}
            status={status}
            brokenFrom={brokenFrom}
          />
        ))}
      </ol>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function VerdictPanel({
  status,
  headHash,
  anchor,
  reversibilityOk,
  tamper,
}: {
  status: Status;
  headHash: string;
  anchor: string | null;
  reversibilityOk: boolean | null;
  tamper: TamperResponse | null;
}) {
  const broken = status === "broken";
  return (
    <section
      className={[
        "rounded border bg-ink-700 p-5 sm:p-6 transition-colors duration-500",
        broken ? "border-vermilion/55" : "border-brass/45",
      ].join(" ")}
      aria-label="Audit status"
    >
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-[0.24em] text-fg-faint">
            Audit Status
          </p>
          {/* Fraunces — ceremonial verdict */}
          <p
            aria-live="polite"
            className={[
              "font-display text-[52px] font-semibold leading-[0.95] tracking-tight",
              broken ? "text-vermilion" : "text-brass-bright",
            ].join(" ")}
          >
            {broken ? "BREAK" : "VALID"}
          </p>
          <p className="mt-1 text-[13px] text-fg-muted">
            {broken
              ? `recomputed head ≠ anchor — broken at record ${
                  tamper?.first_broken_seq ?? "?"
                } (${tamper?.first_broken_type ?? "record"})`
              : "recomputed head ≡ out-of-band anchor"}
          </p>
        </div>

        {!broken && reversibilityOk && (
          <div className="flex items-center gap-2 rounded-sm border border-brass/40 px-2.5 py-1.5">
            <span
              aria-hidden
              className="inline-block h-1.5 w-1.5 rounded-full bg-brass"
            />
            <span className="text-[11px] uppercase tracking-[0.12em] text-brass-bright">
              Reversibility verified
            </span>
          </div>
        )}
      </div>

      <dl className="mt-5 grid gap-x-8 gap-y-3 border-t border-ink-600 pt-4 sm:grid-cols-2">
        <HashField
          label={broken ? "Recomputed head" : "Head"}
          value={headHash}
          tone={broken ? "break" : "ok"}
        />
        <HashField label="Anchor (out-of-band)" value={anchor ?? "—"} tone="neutral" />
      </dl>
    </section>
  );
}

function HashField({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "break" | "neutral";
}) {
  const color =
    tone === "break"
      ? "text-vermilion-bright"
      : tone === "ok"
        ? "text-brass-bright"
        : "text-fg";
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.16em] text-fg-faint">
        {label}
      </dt>
      <dd
        className={`mt-1 break-all font-mono text-[12.5px] leading-relaxed ${color}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

/* -------------------------------------------------------------------------- */

function ChainItem({
  rec,
  index,
  isFirst,
  status,
  brokenFrom,
}: {
  rec: AuditRecord;
  index: number;
  isFirst: boolean;
  status: Status;
  brokenFrom: number | null;
}) {
  const broken =
    status === "broken" && brokenFrom !== null && rec.seq >= brokenFrom;
  const delay = broken && brokenFrom !== null ? (rec.seq - brokenFrom) * STAGGER_MS : 0;
  const isHuman = (rec.sender_type ?? "").toLowerCase() === "user";
  const label = RECORD_LABEL[rec.record_type] ?? rec.record_type;

  const styleVars = { "--cascade-delay": `${delay}ms` } as CSSProperties;

  return (
    <li
      className="citem grid grid-cols-[28px_1fr] gap-x-3"
      data-broken={broken}
      style={styleVars}
    >
      {/* spine column */}
      <div className="flex flex-col items-center">
        <div className={`cspine w-[2px] ${isFirst ? "h-0" : "h-5"}`} aria-hidden />
        <div
          className="cnode h-2.5 w-2.5 rotate-45 border"
          aria-hidden
          title={`link · prev ${shortHash(rec.prev_hash)}`}
        />
        <div className="cspine w-[2px] flex-1" aria-hidden />
      </div>

      {/* record block */}
      <div
        className="cblock grain seal-in relative my-1 overflow-hidden p-4"
        style={{ animationDelay: `${index * 55}ms`, ...styleVars }}
      >
        {isHuman && <span className="haccent" aria-hidden />}
        <span className="cfracture" aria-hidden />

        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-baseline gap-2">
              <span className="tabular font-mono text-[11px] text-bone-ink-muted">
                {String(rec.seq).padStart(2, "0")}
              </span>
              <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-bone-ink-muted">
                {rec.record_type}
              </span>
            </div>
            <h3 className="mt-0.5 text-[16px] font-semibold leading-tight">
              {label}
            </h3>
            <p className="mt-1 text-[12.5px]">
              <span className="font-medium">{rec.sender_name ?? "—"}</span>
              <span className="role-tag ml-2 rounded-sm border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider">
                {isHuman ? "human" : "agent"}
              </span>
            </p>
          </div>

          {/* seal stamp */}
          <span className="cseal shrink-0 rounded-sm px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em]">
            {broken ? "void" : "sealed"}
          </span>
        </div>

        {/* fields */}
        <dl className="cdiv mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 pt-3">
          <Field label="case_id" value={rec.case_id ?? "—"} />
          <Field label="proposal_id" value={rec.proposal_id ?? "—"} />
        </dl>

        <div className="mt-2">
          <span className="text-[10px] uppercase tracking-[0.14em] text-bone-ink-muted">
            entry hash
          </span>
          <p
            className="chash mt-0.5 break-all font-mono text-[12px] leading-relaxed"
            title={rec.entry_hash}
          >
            {shortHash(rec.entry_hash, 16, 10)}
          </p>
        </div>
      </div>
    </li>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[9.5px] uppercase tracking-[0.14em] text-bone-ink-muted">
        {label}
      </dt>
      <dd className="truncate font-mono text-[12px]" title={value}>
        {value}
      </dd>
    </div>
  );
}
