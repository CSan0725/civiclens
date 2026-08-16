import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Members" };

export default function MembersPage() {
  return (
    <ComingSoon
      title="Members"
      route="/members"
      requirement="PRD FR-M1"
    />
  );
}
