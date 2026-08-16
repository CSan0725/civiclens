import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Methodology" };

export default function MethodologyPage() {
  return (
    <ComingSoon
      title="Methodology"
      route="/methodology"
      requirement="PRD §11 · NFR-5"
    />
  );
}
