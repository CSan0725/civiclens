import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Districts" };

export default function DistrictsPage() {
  return (
    <ComingSoon
      title="Find your district"
      route="/districts"
      requirement="PRD FR-G1–FR-G3"
    />
  );
}
