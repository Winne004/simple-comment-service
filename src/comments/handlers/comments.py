"""Comment routes: create, read, reply listing, edit, soft delete."""

from typing import Any

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.metrics import MetricUnit

from comments.handlers.common import (
    json_response,
    parse_max_depth,
    parse_sort,
    require_user_id,
)
from comments.handlers.posts import sort_comments
from comments.models import CreateCommentBody, EditCommentBody
from comments.observability import metrics
from comments.repository import get_repository

router = Router()


@router.post("/posts/<post_id>/comments")
def create_comment(post_id: str) -> Any:
    user_id = require_user_id(router.current_event)
    body = CreateCommentBody.model_validate(router.current_event.json_body)
    comment = get_repository().create_comment(
        post_id, user_id, body.content, parent_id=body.parent_id
    )
    metrics.add_metric(name="CommentsCreated", unit=MetricUnit.Count, value=1)
    return json_response(comment.model_dump(), status_code=201)


@router.get("/posts/<post_id>/comments/<comment_id>")
def get_comment(post_id: str, comment_id: str) -> dict[str, Any]:
    return get_repository().get_comment(post_id, comment_id).model_dump()


@router.get("/posts/<post_id>/comments/<comment_id>/replies")
def get_replies(post_id: str, comment_id: str) -> dict[str, Any]:
    """Descendants of a comment (#4/#6), or direct children with ?direct=true (#5)."""
    event = router.current_event
    sort = parse_sort(event)
    direct = event.query_string_parameters.get("direct") in ("true", "1")
    comments = get_repository().get_subtree(
        post_id,
        comment_id,
        max_depth=parse_max_depth(event),
        include_root=False,
        direct_only=direct,
    )
    return {"items": [c.model_dump() for c in sort_comments(comments, sort)]}


@router.patch("/posts/<post_id>/comments/<comment_id>")
def edit_comment(post_id: str, comment_id: str) -> dict[str, Any]:
    user_id = require_user_id(router.current_event)
    body = EditCommentBody.model_validate(router.current_event.json_body)
    return get_repository().edit_comment(post_id, comment_id, user_id, body.content).model_dump()


@router.delete("/posts/<post_id>/comments/<comment_id>")
def delete_comment(post_id: str, comment_id: str) -> dict[str, Any]:
    user_id = require_user_id(router.current_event)
    return get_repository().delete_comment(post_id, comment_id, user_id).model_dump()
