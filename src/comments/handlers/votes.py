"""Vote routes: cast/change, remove, and read votes."""

from typing import Any

from aws_lambda_powertools.event_handler.api_gateway import Router
from aws_lambda_powertools.event_handler.exceptions import BadRequestError
from aws_lambda_powertools.metrics import MetricUnit

from comments.errors import VoteNotFoundError
from comments.handlers.common import require_user_id
from comments.models import VoteBody
from comments.observability import metrics
from comments.repository import get_repository

router = Router()


@router.put("/posts/<post_id>/comments/<comment_id>/vote")
def cast_vote(post_id: str, comment_id: str) -> dict[str, Any]:
    """V1: returns the comment with updated denormalized counters."""
    user_id = require_user_id(router.current_event)
    body = VoteBody.model_validate(router.current_event.json_body)
    comment = get_repository().cast_vote(post_id, comment_id, user_id, body.value)
    metrics.add_metric(name="VotesCast", unit=MetricUnit.Count, value=1)
    return comment.model_dump()


@router.delete("/posts/<post_id>/comments/<comment_id>/vote")
def remove_vote(post_id: str, comment_id: str) -> dict[str, Any]:
    """V2."""
    user_id = require_user_id(router.current_event)
    return get_repository().remove_vote(post_id, comment_id, user_id).model_dump()


@router.get("/posts/<post_id>/comments/<comment_id>/vote")
def get_vote(post_id: str, comment_id: str) -> dict[str, Any]:
    """V4: how the calling user voted on one comment."""
    user_id = require_user_id(router.current_event)
    vote = get_repository().get_user_vote(post_id, user_id, comment_id)
    if vote is None:
        raise VoteNotFoundError(comment_id)
    return vote.model_dump()


@router.get("/posts/<post_id>/votes")
def list_votes_on_post(post_id: str) -> dict[str, Any]:
    """V5: the calling user's votes across a whole post."""
    user_id = require_user_id(router.current_event)
    votes = get_repository().list_user_votes_on_post(post_id, user_id)
    return {"items": [v.model_dump() for v in votes]}


@router.get("/users/<user_id>/votes")
def list_user_votes(user_id: str) -> dict[str, Any]:
    """V6: a user's votes across all posts; ?value=1 filters to upvotes."""
    raw_value = router.current_event.query_string_parameters.get("value")
    value: int | None = None
    if raw_value is not None:
        if raw_value not in ("1", "-1"):
            raise BadRequestError("value must be 1 or -1")
        value = int(raw_value)
    votes = get_repository().list_user_votes(user_id, value=value)
    return {"items": [v.model_dump() for v in votes]}
