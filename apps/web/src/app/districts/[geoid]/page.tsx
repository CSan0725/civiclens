import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

type Params = { geoid: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { geoid } = await params;
  return { title: `District ${geoid}` };
}

export default async function DistrictDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { geoid } = await params;

  return (
    <ComingSoon
      title="District detail"
      route="/districts/[geoid]"
      requirement="PRD FR-G3–FR-G5 · FR-C2"
    >
      Census GEOID: <code className="font-mono">{geoid}</code>
    </ComingSoon>
  );
}
