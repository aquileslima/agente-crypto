"""
Sentiment Agent — fetches Reddit + Fear & Greed Index data and scores market sentiment.
Uses free public APIs only (no Twitter/X API required).
"""
import json
import logging
import requests
from agents.base_agent import get_client, MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)

REDDIT_HEADERS = {"User-Agent": "ETH-Trading-Bot/1.0 (sentiment analysis)"}
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=3"
REDDIT_SOURCES = [
    ("r/ethtrader", "https://www.reddit.com/r/ethtrader/new.json?limit=20&t=day"),
    ("r/CryptoCurrency", "https://www.reddit.com/r/CryptoCurrency/search.json?q=ethereum+ETH&sort=new&limit=15&t=day"),
]

_SYSTEM_PROMPT = """You are a crypto market sentiment analyst specializing in Ethereum/ETH.

Your task: analyze the provided Reddit posts and Fear & Greed Index data to score overall market sentiment.

SCORING RULES:
- Score 0-20: Extreme Fear (strong contrarian LONG signal)
- Score 21-40: Fear (mild bullish lean)
- Score 41-60: Neutral
- Score 61-80: Greed (mild bearish lean)
- Score 81-100: Extreme Greed (strong contrarian SHORT signal)

Look for: FUD vs FOMO language, key price levels mentioned, whale/institutional mentions,
narrative momentum (are people excited or scared?), technical discussion sentiment.

Respond ONLY with valid JSON — no markdown, no extra text.

OUTPUT FORMAT:
{
  "score": <integer 0-100>,
  "label": "Extreme Fear" | "Fear" | "Neutral" | "Greed" | "Extreme Greed",
  "fear_greed_index": <integer from API or null>,
  "reddit_tone": "bullish" | "bearish" | "neutral",
  "key_themes": ["<theme1>", "<theme2>", "<theme3>"],
  "notable_posts": ["<brief summary of most relevant post>"],
  "reasoning": "<2-3 sentence sentiment summary>"
}"""


def _fetch_fear_greed() -> dict | None:
    try:
        r = requests.get(FEAR_GREED_URL, timeout=8)
        r.raise_for_status()
        data = r.json()
        latest = data["data"][0]
        return {
            "value": int(latest["value"]),
            "label": latest["value_classification"],
            "timestamp": latest["timestamp"],
        }
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
        return None


def _fetch_reddit_posts() -> list[dict]:
    posts = []
    for source_name, url in REDDIT_SOURCES:
        try:
            r = requests.get(url, headers=REDDIT_HEADERS, timeout=10)
            r.raise_for_status()
            children = r.json()["data"]["children"]
            for child in children:
                post = child["data"]
                posts.append(
                    {
                        "source": source_name,
                        "title": post.get("title", "")[:200],
                        "score": post.get("score", 0),
                        "upvote_ratio": post.get("upvote_ratio", 0.5),
                        "num_comments": post.get("num_comments", 0),
                        "selftext": post.get("selftext", "")[:300],
                    }
                )
        except Exception as e:
            logger.warning(f"Reddit fetch failed for {source_name}: {e}")
    # Sort by engagement (score + comments) and return top 20
    posts.sort(key=lambda p: p["score"] + p["num_comments"] * 3, reverse=True)
    return posts[:20]


def analyze(reflect_context: str = "") -> dict:
    """
    Fetch sentiment data and return structured sentiment score.

    Returns:
        dict with keys: score, label, fear_greed_index, reddit_tone,
                        key_themes, notable_posts, reasoning
    """
    client = get_client()

    fear_greed = _fetch_fear_greed()
    posts = _fetch_reddit_posts()

    # Build context for the model
    fg_text = (
        f"Fear & Greed Index: {fear_greed['value']}/100 ({fear_greed['label']})"
        if fear_greed
        else "Fear & Greed Index: unavailable"
    )

    posts_text = ""
    if posts:
        for i, p in enumerate(posts[:15], 1):
            posts_text += (
                f"{i}. [{p['source']}] Score:{p['score']} | "
                f"Comments:{p['num_comments']} | Upvotes:{p['upvote_ratio']:.0%}\n"
                f"   Title: {p['title']}\n"
            )
            if p["selftext"]:
                posts_text += f"   Body: {p['selftext'][:150]}...\n"
    else:
        posts_text = "No Reddit posts available."

    user_content = f"""SENTIMENT DATA — ETH/USDT

{fg_text}

REDDIT POSTS (sorted by engagement):
{posts_text}
"""

    if reflect_context:
        user_content += f"\nHISTORICAL CONTEXT:\n{reflect_context}\n"

    user_content += "\nScore the current market sentiment and return your JSON assessment."

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        logger.info(f"Sentiment score: {result.get('score')} ({result.get('label')})")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Sentiment agent JSON parse error: {e}")
        return {"score": 50, "label": "Neutral", "reasoning": "Parse error", "error": str(e)}
    except Exception as e:
        logger.error(f"Sentiment agent error: {e}")
        return {"score": 50, "label": "Neutral", "reasoning": "Agent error", "error": str(e)}
