import { cn } from "@/lib/utils";

/**
 * Party shown as a NEUTRAL LABELLED CHIP, never a saturated red/blue fill.
 *
 * UIUX-Design-Report, "Neutrality & Trust Design Guidelines" #1: the red/blue
 * mapping only dates to the 2000 election and carries partisan heat. The chip
 * leads with the letter and the full party name; the colour is a small dot
 * drawn from the equal-luminance, equal-chroma party tints in globals.css, so
 * no party reads as louder than another, and it is never the only encoding.
 */

const DOT: Record<string, string> = {
  D: "bg-party-d",
  R: "bg-party-r",
  I: "bg-party-i",
  ID: "bg-party-i",
};

export function PartyChip({
  code,
  name,
  className,
}: {
  code?: string | null;
  name?: string | null;
  className?: string;
}) {
  if (!code && !name) return null;

  const letter = (code ?? name?.[0] ?? "?").toUpperCase();
  const label = name ? `${letter} — ${name}` : letter;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn("size-2 rounded-full", DOT[letter] ?? "bg-party-other")}
      />
      {label}
    </span>
  );
}
