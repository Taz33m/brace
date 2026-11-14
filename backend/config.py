"""Settings and paths. Secrets come from .env and are never logged."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
KIT_DIR = DATA_DIR / "kit"
CACHE_DIR = DATA_DIR / "cache"
BUILDINGS_DIR = CACHE_DIR / "buildings"
HAZARDS_DIR = DATA_DIR / "hazards"

MATTERPORT_API_KEY = os.environ.get("MATTERPORT_API_KEY", "")
MATTERPORT_API_TOKEN = os.environ.get("MATTERPORT_API_TOKEN", "")
MATTERPORT_SDK_KEY = os.environ.get("MATTERPORT_SDK_KEY", "")
VEXCEL_API_KEY = os.environ.get("VEXCEL_API_KEY", "")

# The Anthropic SDK reads its own credentials from the environment. An empty
# value in .env must not shadow another credential source, so drop it.
if os.environ.get("ANTHROPIC_API_KEY") == "":
    del os.environ["ANTHROPIC_API_KEY"]
AGENT_MODEL = os.environ.get("BRACE_AGENT_MODEL") or "claude-opus-5-5"
VISION_MODEL = os.environ.get("BRACE_VISION_MODEL") or "claude-haiku-5-5"
AGENT_EFFORT = os.environ.get("BRACE_AGENT_EFFORT") or "high"
MAX_AGENT_TURNS = int(os.environ.get("BRACE_MAX_TURNS") or 60)

VEXCEL_LAYERS = "urban,urban-r,wide-area,urban-g"

for _d in (CACHE_DIR, BUILDINGS_DIR, HAZARDS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
