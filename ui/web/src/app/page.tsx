import type { Metadata } from "next";
import { getSummary, getAudit, getCases } from "@/lib/api";
import { Dashboard } from "@/components/Dashboard";
import { BridgeOffline } from "@/components/BridgeOffline";

export const metadata: Metadata = {
  title: "Dashboard · Castellan Mission Control",
};

export default async function Home() {
  try {
    const [summary, audit, cases] = await Promise.all([
      getSummary(),
      getAudit(),
      getCases(),
    ]);
    return <Dashboard summary={summary} audit={audit} cases={cases} />;
  } catch (e) {
    return <BridgeOffline error={e instanceof Error ? e.message : null} />;
  }
}
