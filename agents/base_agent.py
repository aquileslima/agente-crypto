import anthropic
import os
import logging
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1024


def get_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in .env")
    return anthropic.Anthropic(api_key=api_key)
