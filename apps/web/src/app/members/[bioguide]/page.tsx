import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

type Params = { bioguide: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { bioguide } = await params;
  return { title: `Member ${bioguide}` };
}

export default async function MemberProfilePage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { bioguide } = await params;

  return (
    <ComingSoon
      title="Member profile"
      route="/members/[bioguide]"
      requirement="PRD FR-M2–FR-M6"
    >
      Bioguide ID: <code className="font-mono">{bioguide}</code>
    </ComingSoon>
  );
}
