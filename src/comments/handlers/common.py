"""Shared helpers for route handlers."""

import json
from typing import Any

from aws_lambda_powertools.event_handler import Response, content_types
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, UnauthorizedError
from aws_lambda_powertools.utilities.data_classes.common import BaseProxyEvent

from comments import keys

USER_ID_HEADER = "x-user-id"

SORT_NEW = "new"
SORT_TOP = "top"


def require_user_id(event: BaseProxyEvent) -> str:
    user_id = event.headers.get(USER_ID_HEADER)
    if not user_id:
        raise UnauthorizedError(f"Missing {USER_ID_HEADER} header")
    return user_id


def parse_max_depth(event: BaseProxyEvent) -> int | None:
    raw = event.query_string_parameters.get("max_depth")
    if raw is None:
        return None
    try:
        max_depth = int(raw)
    except ValueError as exc:
        raise BadRequestError("max_depth must be an integer") from exc
    if not 0 <= max_depth <= keys.MAX_KEYED_DEPTH:
        raise BadRequestError(f"max_depth must be between 0 and {keys.MAX_KEYED_DEPTH}")
    return max_depth


def parse_limit(event: BaseProxyEvent) -> int | None:
    raw = event.query_string_parameters.get("limit")
    if raw is None:
        return None
    try:
        limit = int(raw)
    except ValueError as exc:
        raise BadRequestError("limit must be an integer") from exc
    if limit < 1:
        raise BadRequestError("limit must be >= 1")
    return limit


def parse_sort(event: BaseProxyEvent) -> str:
    sort = event.query_string_parameters.get("sort", SORT_NEW)
    if sort not in (SORT_NEW, SORT_TOP):
        raise BadRequestError(f"sort must be '{SORT_NEW}' or '{SORT_TOP}'")
    return sort


def json_response(body: Any, status_code: int = 200) -> Response:
    return Response(
        status_code=status_code,
        content_type=content_types.APPLICATION_JSON,
        body=json.dumps(body),
    )
