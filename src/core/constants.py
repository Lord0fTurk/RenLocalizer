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

# Microsoft Edge web-translation endpoint (Bing engine). Keyless: no token,
# cookie or API key. Replaced the retired `edge.microsoft.com/translate/auth`
# JWT flow (404 since Aug 2026). Verified live 2026-09-21: accepts a JSON
# array of strings, `textType=html` honours <span class="notranslate">,
# ~50k chars per request is the hard ceiling (HTTP 400 beyond).
BING_EDGE_TRANSLATE_ENDPOINT = "https://edge.microsoft.com/translate/translatetext"

# ── Built-in GGUF runtime (llama.cpp server) ─────────────────────────────────
# RenLocalizer can run a user-supplied .gguf model through llama.cpp's
# OpenAI-compatible server, so no Ollama / LM Studio install is required.
# The build is PINNED: llama.cpp publishes rolling nightly builds (bNNNNN), and
# a fixed tag keeps the artifact — and therefore its SHA256 — predictable.
# GitHub reports a `digest: "sha256:..."` per asset, which is verified after
# download. Nothing is fetched unless the user explicitly asks for it.
LLAMACPP_REPO = "ggml-org/llama.cpp"
LLAMACPP_PINNED_BUILD = "b11120"
LLAMACPP_RELEASE_API = (
    "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{build}"
)
# Used only when the pinned build no longer carries the needed asset.
LLAMACPP_RELEASE_LIST_API = (
    "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"
)
# Seconds to wait for GET /health after launch (large models load slowly).
LLAMACPP_HEALTH_TIMEOUT = 180.0
# Used when local_llm_server_port is 0 (auto) and the port is free; Ollama is
# 11434, LM Studio 1234 and llama-server's own default 8080 — avoid all three.
LLAMACPP_DEFAULT_PORT = 18080
# backend -> platform key -> release asset template.
# Vulkan is the default: ~30 MB, works on NVIDIA/AMD/Intel without CUDA Toolkit.
# CUDA is faster on NVIDIA but needs the 400 MB cudart archive as well.
LLAMACPP_VARIANTS = {
    "vulkan": {
        "win-x64": "llama-{build}-bin-win-vulkan-x64.zip",
        "linux-x64": "llama-{build}-bin-ubuntu-vulkan-x64.tar.gz",
        "linux-arm64": "llama-{build}-bin-ubuntu-vulkan-arm64.tar.gz",
    },
    "cuda": {
        "win-x64": "llama-{build}-bin-win-cuda-12.4-x64.zip",
        "win-arm64": "llama-{build}-bin-win-cuda-13.4-arm64.zip",
        "linux-x64": "llama-{build}-bin-ubuntu-cuda-12.8-x64.tar.gz",
        "linux-arm64": "llama-{build}-bin-ubuntu-cuda-13.4-arm64.tar.gz",
    },
    "cpu": {
        "win-x64": "llama-{build}-bin-win-cpu-x64.zip",
        "win-arm64": "llama-{build}-bin-win-cpu-arm64.zip",
        "linux-x64": "llama-{build}-bin-ubuntu-x64.tar.gz",
        "linux-arm64": "llama-{build}-bin-ubuntu-arm64.tar.gz",
        "macos-x64": "llama-{build}-bin-macos-x64.tar.gz",
        "macos-arm64": "llama-{build}-bin-macos-arm64.tar.gz",
    },
}

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

# ============================================================================
# FILES RENLOCALIZER WRITES INTO game/
# ============================================================================
# Re-scanning these on the next run sent their comments and docstrings
# (Turkish/English helper text) to the translator and skewed source-language
# detection, so source scanners must skip them (.rpy and compiled .rpyc).
import re as _re

_GENERATED_SCRIPT_RE = _re.compile(
    r"^(?:zzz_renlocalizer_runtime|zzz_renlocalizer_font|zzz_[a-z0-9_\-]+_language|zz_rl_exported_.+)\.rpym?c?$",
    _re.IGNORECASE,
)


def is_renlocalizer_generated_script(file_name: str) -> bool:
    """True for scripts RenLocalizer itself generates inside the game folder."""
    return bool(_GENERATED_SCRIPT_RE.match(file_name or ""))
