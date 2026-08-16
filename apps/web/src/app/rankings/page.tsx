import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Rankings" };

export default function RankingsPage() {
  return (
    <ComingSoon
      title="Rankings"
      route="/rankings"
      requirement="PRD FR-R1–FR-R4 · §11"
    />
  );
}
