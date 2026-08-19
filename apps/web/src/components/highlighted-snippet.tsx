import { Fragment } from "react";

import { HL_CLOSE, HL_OPEN } from "@/db/queries";

/**
 * Renders a `ts_headline` snippet with its matched terms marked.
 *
 * Postgres is asked for literal `[[hl]]`/`[[/hl]]` sentinels rather than HTML
 * tags, and they are split here into real elements. `dangerouslySetInnerHTML`
 * on `StartSel=<mark>` output is the shorter way to do this and is not worth
 * it: the string it would inject is derived from Congressional Record text,
 * and there is no reason to hand a rendering path to a document we did not
 * write.
 */
export function HighlightedSnippet({
  snippet,
  className,
}: {
  snippet?: string | null;
  className?: string;
}) {
  if (!snippet) return null;

  return (
    <p className={className}>
      {splitOnHighlights(snippet).map((part, index) => (
        <Fragment key={index}>
          {part.matched ? (
            <mark className="rounded-sm bg-amber-200/70 px-0.5 text-foreground dark:bg-amber-300/30">
              {part.text}
            </mark>
          ) : (
            part.text
          )}
        </Fragment>
      ))}
    </p>
  );
}

/** Exported for the unit test; the sentinels are an implementation detail. */
export function splitOnHighlights(snippet: string): { text: string; matched: boolean }[] {
  const parts: { text: string; matched: boolean }[] = [];
  let rest = snippet;

  while (rest.length > 0) {
    const open = rest.indexOf(HL_OPEN);
    if (open === -1) break;

    const close = rest.indexOf(HL_CLOSE, open + HL_OPEN.length);
    // An unterminated sentinel means the snippet was truncated mid-highlight.
    // Emit the remainder as plain text rather than dropping it.
    if (close === -1) break;

    if (open > 0) parts.push({ text: rest.slice(0, open), matched: false });
    parts.push({ text: rest.slice(open + HL_OPEN.length, close), matched: true });
    rest = rest.slice(close + HL_CLOSE.length);
  }

  if (rest.length > 0) parts.push({ text: rest, matched: false });
  return parts;
}
