"""The project's User-Agent string.

Its own module so `common.settings` can default to it without importing
`common.http`, which imports settings back.
"""

from __future__ import annotations

USER_AGENT = "CivicLens/0.1 (open civic data; +https://github.com/)"
