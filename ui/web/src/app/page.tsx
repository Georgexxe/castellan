import type { Metadata } from "next";
import {
  getSummary,
  getAudit,
  getCases,
  getEvidence,
  ROOM_ID,
  DATA_CASE_ID,
} from "@/lib/api";
import { Dashboard } from "@/components/Dashboard";
import { BridgeOffline } from "@/components/BridgeOffline";

export const metadata: Metadata = {
  title: "Dashboard · Castellan Mission Control",
};

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ room?: string }>;
}) {
  const { room } = await searchParams; // Next 16: searchParams is async
  const roomId = room?.trim() || ROOM_ID;
  try {
    const [summary, audit, cases, evidence] = await Promise.all([
      getSummary(roomId),
      getAudit(roomId),
      getCases(roomId),
      getEvidence(DATA_CASE_ID, roomId),
    ]);
    return (
      <Dashboard
        summary={summary}
        audit={audit}
        cases={cases}
        evidence={evidence}
      />
    );
  } catch (e) {
    return <BridgeOffline error={e instanceof Error ? e.message : null} />;
  }
}
