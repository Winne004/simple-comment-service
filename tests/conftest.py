"""Shared fixtures: environment + a moto DynamoDB table mirroring template.yaml."""

import os

# Must be set before any comments.* / boto3 import touches the environment.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["TABLE_NAME"] = "Comments"
os.environ["POWERTOOLS_TRACE_DISABLED"] = "1"
os.environ["POWERTOOLS_SERVICE_NAME"] = "comments-tests"
os.environ["POWERTOOLS_METRICS_NAMESPACE"] = "SimpleCommentServiceTests"
os.environ["POWERTOOLS_METRICS_DISABLED"] = "true"

from typing import Any  # noqa: E402

import boto3  # noqa: E402
import pytest  # noqa: E402
from moto import mock_aws  # noqa: E402

from comments.repository import CommentRepository  # noqa: E402

TABLE_NAME = os.environ["TABLE_NAME"]


@pytest.fixture
def comments_table() -> Any:
    """Create the Comments table (with GSI1) exactly as template.yaml defines it."""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
        )
        yield table


@pytest.fixture
def repo(comments_table: Any) -> CommentRepository:
    return CommentRepository(TABLE_NAME)
