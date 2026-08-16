import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * P0 placeholder.
 *
 * Every route in PRD §10 exists and renders this, so the information
 * architecture is walkable before any data lands. Replace per-route in P5.
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
            This route is a P0 scaffold. Data collection (P1) and the real
            interface (P5) are still ahead.
          </p>
          {children ? <div className="text-foreground">{children}</div> : null}
        </CardContent>
      </Card>
    </section>
  );
}
