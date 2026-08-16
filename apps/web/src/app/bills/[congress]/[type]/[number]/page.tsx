import type { Metadata } from "next";
import { ComingSoon } from "@/components/coming-soon";

type Params = { congress: string; type: string; number: string };

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { congress, type, number } = await params;
  return { title: `${type.toUpperCase()} ${number} (${congress}th Congress)` };
}

export default async function BillDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { congress, type, number } = await params;

  return (
    <ComingSoon
      title="Bill detail"
      route="/bills/[congress]/[type]/[number]"
      requirement="PRD §10 IA"
    >
      Natural key:{" "}
      <code className="font-mono">
        ({congress}, {type}, {number})
      </code>
    </ComingSoon>
  );
}
