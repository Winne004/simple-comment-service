"""User routes: a user's comments across all posts (GSI1)."""

from typing import Any

from aws_lambda_powertools.event_handler.api_gateway import Router

from comments.handlers.common import parse_limit
from comments.repository import get_repository

router = Router()


@router.get("/users/<user_id>/comments")
def list_user_comments(user_id: str) -> dict[str, Any]:
    """#9 newest-first; ?since= for #10, ?post_id= for #11."""
    event = router.current_event
    comments, next_cursor = get_repository().list_user_comments(
        user_id,
        since=event.query_string_parameters.get("since"),
        post_id=event.query_string_parameters.get("post_id"),
        limit=parse_limit(event),
        cursor=event.query_string_parameters.get("cursor"),
    )
    return {
        "items": [c.model_dump() for c in comments],
        "next_cursor": next_cursor,
    }
