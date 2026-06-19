import type { Metadata } from "next";
import { getCase, DATA_CASE_ID } from "@/lib/api";
import { Lifecycle } from "@/components/Lifecycle";
import { BridgeOffline } from "@/components/BridgeOffline";

export const metadata: Metadata = {
  title: "Lifecycle · Castellan Mission Control",
};

export default async function LifecyclePage() {
  try {
    const detail = await getCase(DATA_CASE_ID);
    return <Lifecycle detail={detail} />;
  } catch (e) {
    return <BridgeOffline error={e instanceof Error ? e.message : null} />;
  }
}
