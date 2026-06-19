import type { Metadata } from "next";
import { getCloudState } from "@/lib/api";
import { Reversibility } from "@/components/Reversibility";
import { BridgeOffline } from "@/components/BridgeOffline";

export const metadata: Metadata = {
  title: "Reversibility · Castellan Mission Control",
};

export default async function ReversibilityPage() {
  try {
    const state = await getCloudState();
    return <Reversibility state={state} />;
  } catch (e) {
    return <BridgeOffline error={e instanceof Error ? e.message : null} />;
  }
}
