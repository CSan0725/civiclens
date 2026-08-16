import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

type Params = { id: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { id } = await params;
  return { title: `Roll call ${id}` };
}

export default async function VoteDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { id } = await params;

  return (
    <ComingSoon
      title="Vote detail"
      route="/votes/[id]"
      requirement="PRD FR-M4 · §10 IA"
    >
      Vote ID: <code className="font-mono">{id}</code>
    </ComingSoon>
  );
}
