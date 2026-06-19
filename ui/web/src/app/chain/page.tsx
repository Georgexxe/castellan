import type { Metadata } from "next";
import { getAudit, type AuditResponse } from "@/lib/api";
import { AuditChain } from "@/components/AuditChain";
import { BridgeOffline } from "@/components/BridgeOffline";

export const metadata: Metadata = {
  title: "Audit Chain · Castellan Mission Control",
};

export default async function ChainPage() {
  let data: AuditResponse | null = null;
  let error: string | null = null;
  try {
    data = await getAudit();
  } catch (e) {
    error = e instanceof Error ? e.message : "unreachable";
  }

  if (!data) return <BridgeOffline error={error} />;
  return <AuditChain data={data} />;
}
