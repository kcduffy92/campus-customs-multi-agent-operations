"""Settings for the Campus Customs agent team (Homework 5).

Everything configurable lives here, so the model name and the limits are set in
one place. The .env file is loaded from Homework 5/.env by explicit path only;
dotenv is never allowed to search parent folders, whose .env sets a different
model.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

# The assignment allows only gpt-6-luna through Portkey. A different OPENAI_MODEL is
# a configuration error, never a silent fallback.
REQUIRED_MODEL = "gpt-6-luna"
MODEL_NAME = os.getenv("OPENAI_MODEL", "").strip() or REQUIRED_MODEL
if MODEL_NAME != REQUIRED_MODEL:
    raise RuntimeError(f"OPENAI_MODEL is {MODEL_NAME!r}; Homework 5 must use only {REQUIRED_MODEL!r}.")

PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").strip().rstrip("/")
PORTKEY_PROVIDER = os.getenv("PORTKEY_PROVIDER", "openai").strip()

# Application-facing MCP connection: the campus-customs server over Streamable HTTP.
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp").strip()

# Optional label written into each run's audit entries (e.g. "problem5-live-test").
RUN_LABEL = os.getenv("AGENT_RUN_LABEL", "").strip() or None

PROMPTS_DIR = BACKEND_DIR / "prompts"
AUDIT_PATH = Path(os.getenv("AUDIT_TRAIL_PATH", "").strip() or ROOT / "output" / "audit_trail.json")

# Delegation guardrails (per ticket run).
MAX_DELEGATION_DEPTH = 3  # boss -> a -> b -> c, never deeper
MAX_DELEGATIONS_PER_TICKET = 8

# Shared usage limits: every agent in one ticket run draws from the same budget.
REQUEST_LIMIT = 30
TOOL_CALLS_LIMIT = 40
TOTAL_TOKENS_LIMIT = 200_000

RESULT_PREVIEW_CHARS = 600


def portkey_api_key() -> str:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError(f"PORTKEY_API_KEY is not set in {ENV_PATH.name} (Homework 5 folder).")
    return key
