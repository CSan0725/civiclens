import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Speeches" };

export default function SpeechesPage() {
  return (
    <ComingSoon
      title="Speeches"
      route="/speeches"
      requirement="PRD FR-S1–FR-S4"
    />
  );
}
