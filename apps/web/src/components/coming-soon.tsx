import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Placeholder for a route in PRD §10 that has no data behind it yet.
 *
 * Introduced in P0 so the whole information architecture was walkable before
 * anything landed. P5 replaced it on /bills, /votes and /rankings. Still
 * rendering it: /districts, which is blocked on the P4 boundary files, and
 * /members and /methodology, which are interface work not yet done (§10
 * footnote 5).
 */
export function ComingSoon({
  title,
  route,
  requirement,
  children,
}: {
  /** Page name as it appears in PRD §10. */
  title: string;
  /** The route pattern, so the IA stays legible while stubbed. */
  route: string;
  /** The PRD requirement ID this page will satisfy. */
  requirement: string;
  /** Resolved dynamic params, when the route has any. */
  children?: React.ReactNode;
}) {
  return (
    <section className="max-w-2xl">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {requirement}
      </p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-1 font-mono text-sm text-muted-foreground">{route}</p>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-base font-medium">Coming soon</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm text-muted-foreground">
          <p>
            This route is a scaffold. It is listed in the site&rsquo;s
            information architecture so the shape of the whole is visible, but
            it has nothing to show yet — either the data behind it has not been
            collected, or the page has not been built.
          </p>
          {children ? <div className="text-foreground">{children}</div> : null}
        </CardContent>
      </Card>
    </section>
  );
}
