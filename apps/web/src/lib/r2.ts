/**
 * Public URLs for objects the ETL publishes to Cloudflare R2.
 *
 * Only the PUBLIC bucket is reachable this way. The provenance snapshot bucket
 * holds raw upstream payloads and is deliberately not world-readable, so
 * nothing in the web app should ever be pointed at it.
 *
 * `R2_PUBLIC_BASE_URL` is server configuration rather than a NEXT_PUBLIC_
 * variable: the finished URL is resolved in a Server Component and passed
 * down, so the browser never has to know the bucket host to compute one.
 */

export function publicBaseUrl(): string | null {
  const base = process.env.R2_PUBLIC_BASE_URL?.trim();
  return base ? base.replace(/\/+$/, "") : null;
}

/**
 * Join the base URL with an object key.
 *
 * Returns null when either half is missing, which is the case a caller has to
 * handle anyway: the boundaries job leaves `topojson_r2_key` NULL when R2 is
 * unconfigured, and a deployment can be missing the base URL.
 */
export function publicObjectUrl(key: string | null | undefined): string | null {
  const base = publicBaseUrl();
  if (!base || !key) return null;
  return `${base}/${key.replace(/^\/+/, "")}`;
}
