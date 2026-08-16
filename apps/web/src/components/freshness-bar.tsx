import { formatDateTime } from "@/lib/format";

/**
 * The "last synced" line the UIUX report makes mandatory.
 *
 * It shows HOW CURRENT THE DATA IS (`data_current_as_of`, the newest upstream
 * timestamp any collector reached), which is a different question from when a
 * job last ran — a job can succeed at 3am and still be serving week-old data.
 *
 * A dataset whose last run failed is named rather than quietly averaged away.
 */
export function FreshnessBar({
  currentAsOf,
  datasets,
}: {
  currentAsOf?: string;
  datasets: {
    dataset: string;
    lastStatus: string | null;
    lastSuccessAt: string | null;
    dataCurrentAsOf: string | null;
  }[];
}) {
  const failing = datasets.filter((d) => d.lastStatus === "failed");
  const collected = datasets.filter((d) => d.lastSuccessAt);

  return (
    <div className="rounded-lg border bg-card px-4 py-3 text-sm" data-numeric>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-medium">Data current as of</span>
        <span className="text-muted-foreground">
          {currentAsOf ? formatDateTime(currentAsOf) : "not yet established"}
        </span>
      </div>

      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
        {collected.length > 0 ? (
          <>
            Collected datasets:{" "}
            {collected.map((d) => d.dataset.replace(/_/g, " ")).join(", ")}.{" "}
          </>
        ) : null}
        This is when the newest upstream record was published, not when the
        collector last ran.
      </p>

      {failing.length > 0 ? (
        <p className="mt-2 text-xs text-destructive">
          Last collection failed for:{" "}
          {failing.map((d) => d.dataset.replace(/_/g, " ")).join(", ")}. Those
          sections may be behind.
        </p>
      ) : null}
    </div>
  );
}
