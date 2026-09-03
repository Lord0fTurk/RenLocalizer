# -*- coding: utf-8 -*-
"""
Core Constants
==============
Centralized configuration constants for the RenLocalizer core.
This file decouples hardcoded values from logic, making updates easier without code changes.
"""

# ============================================================================
# TRANSLATION API ENDPOINTS
# ============================================================================

# Multiple Google Translate endpoints for load balancing and redundancy
GOOGLE_ENDPOINTS = [
    "https://translate.googleapis.com/translate_a/single",
    "https://translate.google.com/translate_a/single",
    "https://translate.google.com.tr/translate_a/single",
    "https://translate.google.co.uk/translate_a/single",
    "https://translate.google.de/translate_a/single",
    "https://translate.google.fr/translate_a/single",
    "https://translate.google.ru/translate_a/single",
    "https://translate.google.jp/translate_a/single",
    "https://translate.google.ca/translate_a/single",
    "https://translate.google.com.au/translate_a/single",
    "https://translate.google.pl/translate_a/single",
    "https://translate.google.es/translate_a/single",
    "https://translate.google.it/translate_a/single",
]

# Lingva Translate instances (Free Google Translate Proxy fallback)
# Tried only after clients5 also fails. Verified 2026-08-24: the three
# below were dropped because their DNS records are gone (gaierror noise);
# the kept five resolve but currently answer 500/403 — monitored for
# recovery. Primary free-fallback role moved to GOOGLE_CLIENTS5_ENDPOINT.
# Check for updates: https://github.com/thedaviddelta/lingva-translate
LINGVA_INSTANCES = [
    "https://lingva.ml",
    "https://translate.plausibility.cloud",
    "https://lingva.lunar.icu",
    "https://translate.projectsegfau.lt",
    "https://lingva.garudalinux.org",
]

# Per-request headers merged over the session's rotating User-Agent.
# Since Feb 2026 Google rejects bare-UA clients with 429 even at low
# volume (see vscode-google-translate issue #112); these browser-grade
# headers are the confirmed minimal set that restores access.
GOOGLE_BROWSER_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://translate.google.com/",
    "Cookie": "CONSENT=YES+cb",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Alternate Google endpoint family (/translate_a/t, Chrome-dictionary
# client). Keeps serving traffic while /translate_a/single is IP-range
# blocked (verified live 2026-08-24). Response shape differs:
#   sl set  -> ["translation"]
#   sl=auto -> [["translation", "detected_lang"]]
GOOGLE_CLIENTS5_ENDPOINT = "https://clients5.google.com/translate_a/t"

# Third Google-family route: TranslateWebserverUi RPC layer (rpcid MkEWBc).
# Fully separate pipeline from both /translate_a/single and clients5;
# verified live 2026-08-24 from an actively blocked IP. Supports true
# multi-text payloads via the f.req array. Response is a length-prefixed
# envelope body; translation lives in inner[1][0][0][5] sentences,
# detected language at inner[0][2].
GOOGLE_BATCHEXECUTE_ENDPOINT = (
    "https://translate.google.com/_/TranslateWebserverUi/data/batchexecute"
)

# User Agents for rotating requests to avoid bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

# ============================================================================
# TIMEOUTS & RETRIES
# ============================================================================

REQUEST_TIMEOUT_TOTAL = 45
REQUEST_TIMEOUT_CONNECT = 10
REQUEST_TIMEOUT_READ = 30

MIRROR_MAX_FAILURES = 5  # Max failures before temp ban
MIRROR_BAN_TIME = 120  # Ban duration in seconds (2 min)

# IP-level 429 circuit breaker: after this many consecutive 429s Google has
# flagged the client IP — all mirror rotation is pointless until the flag
# decays, so requests pause for RATE_LIMIT_LONG_COOLDOWN seconds instead of
# hammering every host in a tight loop.
RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD = 6
RATE_LIMIT_LONG_COOLDOWN = 300
# While the breaker is active, primaries are retried at most once per this
# interval (a single request probes whether the IP flag has decayed).
RATE_LIMIT_PRIMARY_PROBE_INTERVAL = 300
