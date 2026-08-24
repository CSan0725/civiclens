"""One lazily-built S3 client for Cloudflare R2.

Two different things are written to R2 and they do NOT share a bucket:

  * raw payload snapshots (`provenance.snapshot`) — PRIVATE. The byte-level
    audit trail behind PRD NFR-5.
  * pre-simplified district TopoJSON (`geo.topojson`) — PUBLIC, read straight
    from the browser, so the bucket needs public read and a CORS rule
    (Deployment-Architecture-Report §2c).

The credentials and the endpoint are the same for both; only the bucket name
differs, and the bucket is a per-call argument in the S3 API. So the client
lives here, once, and each caller names its own bucket.

R2 IS OPTIONAL AT RUNTIME. When credentials are absent this returns None after
warning once, and callers degrade instead of failing — a missing bucket must
not be able to take the pipeline down.
"""

from __future__ import annotations

import threading
from typing import Any

from common.logging import get_logger
from common.settings import get_settings

log = get_logger(__name__)

_client_lock = threading.Lock()
_client: Any | None = None
_warned = False

# CORS for the PUBLIC bucket. Measured 2026-08-24: an object in
# `civiclens-public` is readable over its r2.dev URL with plain curl, but the
# response carries no `Access-Control-Allow-Origin` and a preflight OPTIONS
# returns 403. Public-read and CORS are separate switches in R2, so without
# this rule the map's `fetch()` is blocked by the browser even though the
# bytes are world-readable.
#
# `*` for origins, deliberately: the object is already public to anyone with
# curl, so the rule grants a browser nothing it could not otherwise have, and
# pinning the production domain would break every Vercel preview deployment,
# which gets its own hostname. GET/HEAD only — the browser never writes.
PUBLIC_CORS_RULES: list[dict[str, Any]] = [
    {
        "AllowedOrigins": ["*"],
        "AllowedMethods": ["GET", "HEAD"],
        "AllowedHeaders": ["*"],
        "ExposeHeaders": ["ETag", "Content-Length"],
        "MaxAgeSeconds": 86400,
    }
]


def is_configured() -> bool:
    """True when enough R2 settings are present to attempt a request."""
    s = get_settings()
    return bool(s.r2_access_key_id and s.r2_secret_access_key and s.r2_endpoint)


def get_client() -> Any | None:
    """The shared S3 client, or None when R2 is not configured.

    The warning is emitted once per process: a job that uploads per record
    would otherwise print it thousands of times.
    """
    global _client, _warned

    if not is_configured():
        with _client_lock:
            if not _warned:
                log.warning(
                    "r2.not_configured",
                    detail=(
                        "R2 credentials absent, so R2 writes are skipped. Collection "
                        "continues; only the object-storage side effect is lost."
                    ),
                )
                _warned = True
        return None

    with _client_lock:
        if _client is None:
            import boto3  # imported lazily: unused when R2 is unconfigured

            s = get_settings()
            _client = boto3.client(
                "s3",
                endpoint_url=s.r2_endpoint,
                aws_access_key_id=s.r2_access_key_id,
                aws_secret_access_key=s.r2_secret_access_key,
                region_name="auto",
            )
    return _client


def ensure_public_cors() -> bool:
    """Apply `PUBLIC_CORS_RULES` to the public bucket. True when it took.

    Idempotent, and cheap enough to run on every publish: `boundaries` is a
    manual once-per-Congress job, so this is one extra request against a
    handful. Running it here rather than clicking it into the Cloudflare
    dashboard is the point — the bucket's browser-facing contract is then in
    version control, and a bucket rebuilt from scratch gets it back.

    NOT fatal when it fails. Bucket-configuration calls need an R2 token
    scoped "Admin Read & Write"; an "Object Read & Write" token uploads
    objects fine and gets AccessDenied here. Refusing to publish the map
    because the CORS rule could not be re-asserted would be the wrong trade,
    so this warns and returns False.
    """
    client = get_client()
    if client is None:
        return False

    bucket = get_settings().r2_public_bucket
    try:
        client.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": PUBLIC_CORS_RULES})
    except Exception as exc:
        log.warning(
            "r2.cors_not_applied",
            bucket=bucket,
            error=f"{type(exc).__name__}: {exc}",
            detail=(
                "The object is still uploaded and publicly readable, but a browser "
                "fetch() from another origin will be blocked until this rule is "
                "applied. AccessDenied means the R2 token is object-scoped; bucket "
                "configuration needs an Admin Read & Write token."
            ),
        )
        return False

    log.info("r2.cors_applied", bucket=bucket, rules=len(PUBLIC_CORS_RULES))
    return True


def reset_client() -> None:
    """Drop the cached client. Tests use this after changing settings."""
    global _client, _warned
    with _client_lock:
        _client = None
        _warned = False
