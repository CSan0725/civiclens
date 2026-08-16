import { ExternalLink } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * "View original source" — required on every displayed fact (PRD FC-5, NFR-5),
 * modelled on poliwiki's persistent source footer and Our World in Data's
 * per-chart provenance.
 *
 * Renders nothing when there is no URL rather than a dead link: a provenance
 * affordance that goes nowhere is worse than none, because it implies a
 * traceability we do not have.
 */
export function SourceLink({
  href,
  label = "View source",
  className,
}: {
  href?: string | null;
  label?: string;
  className?: string;
}) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline",
        className,
      )}
    >
      {label}
      <ExternalLink aria-hidden className="size-3" />
    </a>
  );
}

/**
 * An honest empty state.
 *
 * PRD FR-S4/FR-C4 and the project's own rules require coverage limits to be
 * stated, not implied. A section with no data is HIDDEN nowhere in this app —
 * it says why it is empty, so "we have not collected this yet" can never be
 * mistaken for "there is nothing to report".
 */
export function EmptyState({
  title,
  detail,
  className,
}: {
  title: string;
  detail?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground",
        className,
      )}
    >
      <p className="font-medium text-foreground">{title}</p>
      {detail ? <p className="mt-1 leading-relaxed">{detail}</p> : null}
    </div>
  );
}
