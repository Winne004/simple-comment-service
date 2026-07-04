"""Lambda entrypoint: Powertools HTTP API resolver + central error mapping."""

import json
from typing import Any

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response, content_types
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import ValidationError

from comments.errors import DomainError
from comments.handlers import comments as comments_handlers
from comments.handlers import posts as posts_handlers
from comments.handlers import users as users_handlers
from comments.handlers import votes as votes_handlers
from comments.observability import logger, metrics, tracer

app = APIGatewayHttpResolver()
app.include_router(posts_handlers.router)
app.include_router(comments_handlers.router)
app.include_router(votes_handlers.router)
app.include_router(users_handlers.router)


def _error_response(status_code: int, error_code: str, message: Any) -> Response:
    return Response(
        status_code=status_code,
        content_type=content_types.APPLICATION_JSON,
        body=json.dumps({"error": error_code, "message": message}),
    )


@app.exception_handler(DomainError)
def handle_domain_error(exc: DomainError) -> Response:
    logger.info("Domain error", error=exc.error_code, detail=exc.message)
    return _error_response(exc.status_code, exc.error_code, exc.message)


@app.exception_handler(ValidationError)
def handle_validation_error(exc: ValidationError) -> Response:
    return _error_response(
        400,
        "validation_error",
        [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()],
    )


@app.exception_handler(json.JSONDecodeError)
def handle_bad_json(exc: json.JSONDecodeError) -> Response:
    return _error_response(400, "invalid_json", "Request body is not valid JSON")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(event, context)
