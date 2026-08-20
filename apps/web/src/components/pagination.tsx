import Link from "next/link";

/**
 * Previous/next pagination that preserves the filters already in the URL.
 *
 * Links rather than buttons, and the whole state lives in the query string, so
 * a filtered page of results is a shareable address and the pages stay
 * server-rendered. Undefined and empty params are dropped so a default filter
 * never shows up in the URL as noise.
 */
export function Pagination({
  basePath,
  params,
  page,
  lastPage,
}: {
  basePath: string;
  params: Record<string, string | number | undefined>;
  page: number;
  lastPage: number;
}) {
  if (lastPage <= 1) return null;

  const href = (n: number) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      search.set(key, String(value));
    }
    if (n > 1) search.set("page", String(n));
    const qs = search.toString();
    return qs ? `${basePath}?${qs}` : basePath;
  };

  return (
    <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
      {page > 1 ? (
        <Link href={href(page - 1)} className="underline-offset-2 hover:underline">
          ← Previous
        </Link>
      ) : (
        <span />
      )}
      <span className="text-muted-foreground" data-numeric>
        Page {page} of {lastPage}
      </span>
      {page < lastPage ? (
        <Link href={href(page + 1)} className="underline-offset-2 hover:underline">
          Next →
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
