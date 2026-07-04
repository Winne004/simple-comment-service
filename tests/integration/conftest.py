"""Handler-level fixtures: drive lambda_handler with API Gateway v2 events."""

import json
from typing import Any

import pytest

from comments import repository


class FakeLambdaContext:
    function_name = "comments-test"
    function_version = "$LATEST"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:comments-test"
    aws_request_id = "00000000-0000-0000-0000-000000000000"
    log_group_name = "/aws/lambda/comments-test"
    log_stream_name = "test-stream"

    def get_remaining_time_in_millis(self) -> int:
        return 30_000


def make_event(
    method: str,
    path: str,
    body: Any | None = None,
    user: str | None = None,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if user is not None:
        headers["x-user-id"] = user
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "&".join(f"{k}={v}" for k, v in (query or {}).items()),
        "headers": headers,
        "queryStringParameters": query or {},
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "test-api",
            "domainName": "test.execute-api.us-east-1.amazonaws.com",
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "test-request",
            "routeKey": "$default",
            "stage": "$default",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


class ApiClient:
    """Calls the real lambda_handler and decodes the JSON response."""

    def request(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        user: str | None = None,
        query: dict[str, str] | None = None,
        raw_body: str | None = None,
    ) -> tuple[int, Any]:
        from comments.app import lambda_handler

        event = make_event(method, path, body=body, user=user, query=query)
        if raw_body is not None:
            event["body"] = raw_body
        result = lambda_handler(event, FakeLambdaContext())  # type: ignore[arg-type]
        payload = json.loads(result["body"]) if result.get("body") else None
        return result["statusCode"], payload


@pytest.fixture
def client(comments_table: Any) -> Any:
    repository.reset_repository()
    yield ApiClient()
    repository.reset_repository()


@pytest.fixture
def post_id(client: ApiClient) -> str:
    status, body = client.request("POST", "/posts", body={"title": "A post"}, user="op")
    assert status == 201
    return body["post_id"]
