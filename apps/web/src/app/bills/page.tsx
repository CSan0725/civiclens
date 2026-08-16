import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Bills" };

export default function BillsPage() {
  return (
    <ComingSoon title="Bills" route="/bills" requirement="PRD §10 IA" />
  );
}
