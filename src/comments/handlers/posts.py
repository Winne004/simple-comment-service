"""Post routes: create/read post metadata and read comment trees."""

from typing import Any

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.metrics import MetricUnit

from comments.handlers.common import (
    SORT_TOP,
    json_response,
    parse_limit,
    parse_max_depth,
    parse_sort,
    require_user_id,
)
from comments.models import Comment, CreatePostBody
from comments.observability import metrics
from comments.repository import get_repository

router = Router()


def sort_comments(comments: list[Comment], sort: str) -> list[Comment]:
    """V7: 'top' sorts by score in the handler; queries return path order."""
    if sort == SORT_TOP:
        return sorted(comments, key=lambda c: c.score, reverse=True)
    return comments


@router.post("/posts")
def create_post() -> Any:
    require_user_id(router.current_event)
    body = CreatePostBody.model_validate(router.current_event.json_body)
    post = get_repository().create_post(body.title)
    metrics.add_metric(name="PostsCreated", unit=MetricUnit.Count, value=1)
    return json_response(post.model_dump(), status_code=201)


@router.get("/posts/<post_id>")
def get_post(post_id: str) -> dict[str, Any]:
    return get_repository().get_post(post_id).model_dump()


@router.get("/posts/<post_id>/comments")
def get_tree(post_id: str) -> dict[str, Any]:
    event = router.current_event
    sort = parse_sort(event)
    comments, next_cursor = get_repository().get_tree(
        post_id,
        max_depth=parse_max_depth(event),
        limit=parse_limit(event),
        cursor=event.query_string_parameters.get("cursor"),
    )
    return {
        "items": [c.model_dump() for c in sort_comments(comments, sort)],
        "next_cursor": next_cursor,
    }
