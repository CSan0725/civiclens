/**
 * The small stacked bar the dashboard blueprint asks for, beside a roll call.
 *
 * Rules it follows, from UIUX-Design-Report:
 *   - the exact counts are always shown as text, never only as a bar;
 *   - segments use a neutral light-to-dark ramp of ONE hue, not green/red,
 *     which would read as good/bad on what is just a recorded position;
 *   - the bar carries role="img" with a full text label, so a screen reader
 *     gets the tally rather than four unlabelled divs.
 */

const SEGMENTS = [
  { key: "Yea", className: "bg-primary" },
  { key: "Nay", className: "bg-primary/45" },
  { key: "Present", className: "bg-muted-foreground/40" },
  { key: "Not voting", className: "bg-muted-foreground/20" },
] as const;

export function VoteTally({
  yea,
  nay,
  present,
  notVoting,
}: {
  yea?: number | null;
  nay?: number | null;
  present?: number | null;
  notVoting?: number | null;
}) {
  const counts = [yea ?? 0, nay ?? 0, present ?? 0, notVoting ?? 0];
  const total = counts.reduce((a, b) => a + b, 0);

  if (total === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No per-position tally reported for this roll call.
      </p>
    );
  }

  const label = SEGMENTS.map((s, i) => `${s.key} ${counts[i]}`).join(", ");

  return (
    <div className="space-y-1.5" data-numeric>
      <div
        role="img"
        aria-label={`Vote tally: ${label}`}
        className="flex h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        {SEGMENTS.map((s, i) =>
          counts[i] > 0 ? (
            <div
              key={s.key}
              className={s.className}
              style={{ width: `${(counts[i] / total) * 100}%` }}
            />
          ) : null,
        )}
      </div>
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
        {SEGMENTS.map((s, i) => (
          <span key={s.key}>
            <span className="font-medium text-foreground">{counts[i]}</span>{" "}
            {s.key}
          </span>
        ))}
      </p>
    </div>
  );
}

/**
 * A member's own recorded position.
 *
 * `position` is NULL and `rawPosition` carries the source string when the cast
 * falls outside the enum — an Election of the Speaker records candidate names.
 * That string is shown VERBATIM and never folded into Yea/Nay (migration 0003,
 * PRD §11 footnote 1, FC-4).
 */
export function PositionBadge({
  position,
  rawPosition,
}: {
  position?: string | null;
  rawPosition?: string | null;
}) {
  if (!position && rawPosition) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-0.5 text-xs">
        <span className="text-muted-foreground">voted for</span>
        <span className="font-medium">{rawPosition}</span>
      </span>
    );
  }

  const label = position === "NotVoting" ? "Not voting" : (position ?? "—");
  return (
    <span className="inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium">
      {label}
    </span>
  );
}
