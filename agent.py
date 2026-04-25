import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilyCrawl, TavilyExtract, TavilyMap, TavilySearch

# Load environment variables from .env
load_dotenv()

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


def get_research_agent():
    """
    Initializes and returns a LangChain agent equipped with Tavily web tools.
    """
    tavily_search = TavilySearch(max_results=5, topic="general")
    tavily_extract = TavilyExtract()
    tavily_crawl = TavilyCrawl()
    tavily_map = TavilyMap()

    model = ChatOpenAI(model_name="gpt-4o")

    today_date = datetime.today().strftime("%B %d, %Y")
    system_prompt = (
        f"You are a helpful research assistant. Today's date is {today_date}. "
        "Use web search to find accurate, up-to-date information. "
        "When the user asks about a specific website or page, prefer Tavily "
        "extract, crawl, or map tools to inspect the source directly instead "
        "of relying only on search."
    )

    agent = create_agent(
        model=model,
        tools=[tavily_search, tavily_extract, tavily_crawl, tavily_map],
        system_prompt=system_prompt,
    )

    return agent


async def run_research(query: str, history: list[dict] | None = None):
    """
    Runs a research query through the agent and returns the response.
    """
    agent = get_research_agent()

    messages = history or []
    messages.append({"role": "user", "content": query})

    response = await agent.ainvoke({"messages": messages})

    return response["messages"][-1].content


def _extract_instagram_username(url: str) -> str | None:
    parsed = parse.urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    return parts[0]


def _extract_first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _extract_count(label: str, text: str) -> int | None:
    value = _extract_first_match(rf"([\d,]+)\s+{label}", text)
    if not value:
        return None
    return int(value.replace(",", ""))


def _parse_instagram_profile(
    url: str, raw_content: str | None, images: list[str]
) -> dict[str, Any]:
    content = raw_content or ""
    username = _extract_instagram_username(url)

    display_name = _extract_first_match(r"^#\s+(.+)$", content)
    bio = _extract_first_match(r"Bio\s*\n+(.+?)(?:\n{2,}|\Z)", content)
    if not bio:
        bio = _extract_first_match(
            rf"{re.escape(username or '')}\s*\([^)]*\)\s*(.+)", content
        )

    external_url = _extract_first_match(r"(https?://[^\s)]+)", content)
    profile_image_url = images[0] if images else None

    return {
        "username": username,
        "display_name": display_name,
        "bio": bio,
        "post_count": _extract_count("posts", content),
        "follower_count": _extract_count("followers", content),
        "following_count": _extract_count("following", content),
        "external_url": external_url,
        "profile_image_url": profile_image_url,
    }


def _run_tavily_extract(
    url: str,
    query: str | None,
    extract_depth: str,
    include_images: bool,
) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY environment variable is not set")

    payload: dict[str, Any] = {
        "urls": url,
        "extract_depth": extract_depth,
        "include_images": include_images,
        "include_favicon": True,
        "format": "markdown",
    }
    if query:
        payload["query"] = query

    req = request.Request(
        TAVILY_EXTRACT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Tavily Extract request failed with status {exc.code}: {body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Tavily Extract network error: {exc.reason}") from exc


async def run_extract_research(
    url: str,
    query: str | None = None,
    extract_depth: str = "advanced",
    include_images: bool = True,
) -> dict[str, Any]:
    tavily_response = await asyncio.to_thread(
        _run_tavily_extract, url, query, extract_depth, include_images
    )

    results = tavily_response.get("results", [])
    failed_results = tavily_response.get("failed_results", [])

    if results:
        result = results[0]
        raw_content = result.get("raw_content")
        images = result.get("images") or []
        platform = "instagram" if "instagram.com" in url.lower() else "web"
        profile = None
        if platform == "instagram":
            profile = _parse_instagram_profile(url, raw_content, images)

        return {
            "url": result.get("url", url),
            "platform": platform,
            "extract_depth": extract_depth,
            "raw_content": raw_content,
            "images": images,
            "favicon": result.get("favicon"),
            "profile": profile,
            "failed": False,
            "error": None,
            "tavily_request_id": tavily_response.get("request_id"),
            "tavily_response_time": tavily_response.get("response_time"),
        }

    failure = failed_results[0] if failed_results else {}
    return {
        "url": failure.get("url", url),
        "platform": "instagram" if "instagram.com" in url.lower() else "web",
        "extract_depth": extract_depth,
        "raw_content": None,
        "images": [],
        "favicon": None,
        "profile": None,
        "failed": True,
        "error": failure.get("error", "No extraction results returned"),
        "tavily_request_id": tavily_response.get("request_id"),
        "tavily_response_time": tavily_response.get("response_time"),
    }
