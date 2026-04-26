import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.prebuilt import create_react_agent
from sqlalchemy.orm import Session

import models

load_dotenv()

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


def make_detour_agent(
    db: Session,
    current_user: models.User,
    created_detour_ids: list[int] | None = None,
):
    tavily_search = TavilySearch(max_results=5, topic="general")

    @tool
    def list_events() -> str:
        """List all available events on the platform."""
        events = db.query(models.Event).limit(20).all()
        if not events:
            return "No events available."
        return "\n".join(
            f"ID:{e.id} - {e.title}: {e.description or 'No description'}"
            for e in events
        )

    @tool
    def search_events(query: str) -> str:
        """Search events on the platform by keyword.

        Args:
            query: Keyword to search event titles and descriptions.
        """
        events = db.query(models.Event).all()
        q = query.lower()
        matched = [
            e
            for e in events
            if q in (e.title or "").lower() or q in (e.description or "").lower()
        ]
        if not matched:
            return "No matching events found."
        return "\n".join(
            f"ID:{e.id} - {e.title}: {e.description or 'No description'}"
            for e in matched[:10]
        )

    @tool
    def get_my_passport() -> str:
        """Get the current user's passport: their profile and attended events."""
        attended = [e.title for e in current_user.attended_events]
        return (
            f"User: {current_user.username}\n"
            f"Profile: {current_user.description or 'No profile set'}\n"
            f"Attended: {', '.join(attended) if attended else 'None'}"
        )

    @tool
    def create_detour(name: str, description: str, event_ids: list[int]) -> str:
        """Create and save a detour (itinerary) for the user.

        Args:
            name: Short name for the detour.
            description: A sentence describing the detour.
            event_ids: Ordered list of platform event IDs to include as stops.
        """
        db_detour = models.Detour(
            name=name,
            description=description,
            user_id=current_user.id,
        )
        db.add(db_detour)
        db.flush()

        stops = []
        for index, event_id in enumerate(event_ids):
            event = db.query(models.Event).filter(models.Event.id == event_id).first()
            if event:
                db.add(
                    models.DetourEvent(
                        detour_id=db_detour.id, event_id=event.id, order=index
                    )
                )
                stops.append(event.title)

        db.commit()
        db.refresh(db_detour)

        if created_detour_ids is not None:
            created_detour_ids.append(int(db_detour.id))

        return (
            f"Detour '{name}' created (ID:{db_detour.id}). "
            f"Stops: {' → '.join(stops) if stops else 'none'}"
        )

    model = ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    today = datetime.today().strftime("%B %d, %Y")
    system_prompt = (
        f"You are a detour planning assistant. Today is {today}. "
        "Help users discover and plan detours (itineraries) using events on "
        "the platform and web research. "
        "Use list_events or search_events to find platform events, "
        "use tavily_search for web research and local inspiration, "
        "then call create_detour to save the itinerary for the user. "
        "Always call create_detour when the user asks to plan or create a detour."
    )

    return create_react_agent(
        model,
        [tavily_search, list_events, search_events, get_my_passport, create_detour],
        prompt=system_prompt,
    )


async def run_detour_agent(
    query: str,
    db: Session,
    current_user: models.User,
    history: list[dict] | None = None,
    created_detour_ids: list[int] | None = None,
) -> str:
    agent = make_detour_agent(db, current_user, created_detour_ids)
    messages = list(history or [])
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


async def run_plan_generation(group_context: str) -> list[dict]:
    """
    Generates a structured city guide plan from group context using a direct LLM call.
    Returns a list of step dicts with phase, title, and detail keys.
    """
    model = ChatOpenAI(
        model=os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    prompt = (
        f"{group_context}\n\n"
        "Based on this group's profiles, budgets, and favorites, generate a Boston city guide plan. "
        "Return ONLY a JSON array of 3 to 5 steps — no markdown, no explanation. Each step must have:\n"
        '  "phase": a short time label (e.g. "morning", "afternoon", "evening")\n'
        '  "title": a short activity title (under 8 words)\n'
        '  "detail": one or two sentences describing the activity\n\n'
        "Example:\n"
        '[{"phase": "morning", "title": "Coffee walk through Beacon Hill", '
        '"detail": "Start at a local cafe and stroll the gas-lit streets."}]'
    )

    response = await model.ainvoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)

    try:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if match:
            steps = json.loads(match.group())
            if isinstance(steps, list):
                return steps
    except (json.JSONDecodeError, AttributeError):
        pass

    return [
        {"phase": "morning", "title": "Group meetup", "detail": "Gather and align on the day's plan."},
        {"phase": "afternoon", "title": "Explore top picks", "detail": "Visit the group's highest-voted favorites."},
        {"phase": "evening", "title": "Group dinner", "detail": "Wrap up with a meal that fits everyone's budget."},
    ]


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
