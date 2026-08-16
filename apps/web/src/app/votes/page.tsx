import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Votes" };

export default function VotesPage() {
  return (
    <ComingSoon title="Votes" route="/votes" requirement="PRD §10 IA" />
  );
}
