// Thin client for the Castellan FastAPI read-bridge. The browser never holds Band
// creds — it only reads this server-side bridge. Real data only; never mocked.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export const ROOM_ID =
  process.env.NEXT_PUBLIC_ROOM_ID ?? "eb4379c9-165a-4139-bc8a-dd166f8280d8";

export type RecordType =
  | "case_open"
  | "contribution"
  | "constraint"
  | "human_approval"
  | "action_applied"
  | "human_rollback"
  | "action_rolled_back";

export interface AuditRecord {
  seq: number;
  prev_hash: string;
  entry_hash: string;
  record_type: RecordType | string;
  case_id: string | null;
  proposal_id: string | null;
  sender_name: string | null;
  sender_type: string | null;
  inserted_at: string;
  payload: Record<string, unknown>;
}

export interface ReversibilityCheck {
  proposal_id: string;
  recomputed: boolean;
  posted: boolean;
  match: boolean;
  ok: boolean;
}

export interface AuditResponse {
  room_id: string;
  head: string;
  anchor: string | null;
  ok: boolean;
  status: "VALID" | "BREAK" | "NO_ANCHOR";
  length: number;
  reversibility: ReversibilityCheck[];
  reversibility_ok: boolean | null;
  records: AuditRecord[];
}

export interface TamperResponse {
  mutated_record_type: string;
  original_head: string;
  tampered_head: string;
  anchor: string | null;
  break: boolean;
  first_broken_seq: number | null;
  first_broken_type: string | null;
  invalidated_after: number;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`bridge ${res.status} for ${path}`);
  }
  return (await res.json()) as T;
}

export const getAudit = (roomId: string = ROOM_ID) =>
  getJSON<AuditResponse>(`/rooms/${roomId}/audit`);

export const getTamper = (roomId: string = ROOM_ID) =>
  getJSON<TamperResponse>(`/rooms/${roomId}/tamper-demo`);

export interface SummaryResponse {
  findings: number;
  cases: number;
  proposals: number;
  verdicts: string[];
  approvals: number;
  rollback_requests: number;
  applied: number;
  rolled_back: number;
  audit: "VALID" | "BREAK" | "NO_ANCHOR";
  audit_ok: boolean;
  reversibility_ok: boolean | null;
}

export interface CaseOverview {
  case_id: string;
  case_key: string | null;
  cls: string | null;
  resource: string | null;
  status: string;
  record_count: number;
  proposal_id: string | null;
  first_seen: string;
}

export interface CaseDetail {
  case_id: string;
  case_key: string | null;
  cls: string | null;
  resource: string | null;
  status: string;
  proposal_id: string | null;
  records: AuditRecord[];
}

export type PAB = {
  BlockPublicAcls: boolean;
  IgnorePublicAcls: boolean;
  BlockPublicPolicy: boolean;
  RestrictPublicBuckets: boolean;
} | null;

export interface CloudState {
  proposal_id: string | null;
  case_id: string | null;
  before: PAB;
  after_apply: PAB;
  after_rollback: PAB;
  restored_matches_original: boolean | null;
}

export const getSummary = (roomId: string = ROOM_ID) =>
  getJSON<SummaryResponse>(`/rooms/${roomId}/summary`);

export const getCases = (roomId: string = ROOM_ID) =>
  getJSON<CaseOverview[]>(`/rooms/${roomId}/cases`);

export const getCase = (caseId: string, roomId: string = ROOM_ID) =>
  getJSON<CaseDetail>(`/rooms/${roomId}/case/${caseId}`);

export const getCloudState = (roomId: string = ROOM_ID) =>
  getJSON<CloudState>(`/rooms/${roomId}/cloud-state`);

export interface EvidenceSummary {
  case_id: string;
  summary: string;
  sender: string | null;
  inserted_at: string;
}

// Evidence Analyst's plain-language summary for a case. null when none exists yet.
export const getEvidence = (caseId: string, roomId: string = ROOM_ID) =>
  getJSON<EvidenceSummary | null>(`/rooms/${roomId}/evidence/${caseId}`);

// The data case that runs the full lifecycle (acme-public-data).
export const DATA_CASE_ID = "575e729d";

// Humanized record-type labels (Archivo). Raw type is shown in mono alongside.
export const RECORD_LABEL: Record<string, string> = {
  case_open: "Case Opened",
  contribution: "Proposal",
  constraint: "Risk Verdict",
  human_approval: "Human Approval",
  action_applied: "Action Applied",
  human_rollback: "Human Rollback",
  action_rolled_back: "Action Rolled Back",
};

export function shortHash(hash: string, head = 10, tail = 6): string {
  if (!hash || hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}
