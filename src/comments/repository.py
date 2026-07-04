"""All DynamoDB access for the comment service.

This is the only module that imports boto3. Key construction is delegated to
keys.py; access patterns are numbered as in CLAUDE.md.
"""

import base64
import binascii
import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError
from ulid import ULID

from comments import keys
from comments.errors import (
    CommentDeletedError,
    CommentNotFoundError,
    ForbiddenError,
    InvalidCursorError,
    PostNotFoundError,
    VoteConflictError,
    VoteNotFoundError,
)
from comments.models import Comment, Post, Vote


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _new_ulid() -> str:
    return str(ULID())


def _encode_cursor(last_evaluated_key: dict[str, Any] | None) -> str | None:
    if last_evaluated_key is None:
        return None
    raw = json.dumps(last_evaluated_key).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    try:
        decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidCursorError() from exc
    if not isinstance(decoded, dict):
        raise InvalidCursorError()
    return decoded


def _comment_from_item(item: dict[str, Any]) -> Comment:
    return Comment(
        comment_id=item["comment_id"],
        post_id=item["post_id"],
        user_id=item["user_id"],
        parent_id=item.get("parent_id"),
        path=item["path"],
        depth=int(item["depth"]),
        content=item["content"],
        created_at=item["created_at"],
        updated_at=item["updated_at"],
        deleted=bool(item["deleted"]),
        upvotes=int(item["upvotes"]),
        downvotes=int(item["downvotes"]),
        score=int(item["score"]),
    )


def _vote_from_item(item: dict[str, Any]) -> Vote:
    return Vote(
        post_id=item["post_id"],
        comment_id=item["comment_id"],
        user_id=item["user_id"],
        value=int(item["value"]),
        created_at=item["created_at"],
        updated_at=item["updated_at"],
    )


def compute_vote_deltas(prev: int | None, new: int | None) -> tuple[int, int, int]:
    """Counter deltas (upvotes, downvotes, score) for a prev -> new transition.

    A value of None means "no vote" (the vote item is absent).
    """
    up = (1 if new == 1 else 0) - (1 if prev == 1 else 0)
    down = (1 if new == -1 else 0) - (1 if prev == -1 else 0)
    return up, down, up - down


class CommentRepository:
    def __init__(self, table_name: str, dynamodb: Any | None = None) -> None:
        self._dynamodb = dynamodb or boto3.resource("dynamodb")
        self._table = self._dynamodb.Table(table_name)
        # The resource-derived client applies the attribute-value
        # transformation, so transact_write_items below takes plain Python
        # values (no manual TypeSerializer step).
        self._client = self._dynamodb.meta.client
        self._table_name = table_name

    # -- Posts ---------------------------------------------------------------

    def create_post(self, title: str) -> Post:
        post_id = _new_ulid()
        post = Post(post_id=post_id, title=title, created_at=_now_iso())
        self._table.put_item(
            Item={
                "PK": keys.post_pk(post_id),
                "SK": keys.POST_META_SK,
                **post.model_dump(),
            }
        )
        return post

    def get_post(self, post_id: str) -> Post:
        """Access pattern #1."""
        result = self._table.get_item(Key={"PK": keys.post_pk(post_id), "SK": keys.POST_META_SK})
        item = result.get("Item")
        if item is None:
            raise PostNotFoundError(post_id)
        return Post(post_id=item["post_id"], title=item["title"], created_at=item["created_at"])

    # -- Comments ------------------------------------------------------------

    def create_comment(
        self, post_id: str, user_id: str, content: str, parent_id: str | None = None
    ) -> Comment:
        """Access pattern #12. Parent existence is guaranteed because deletes
        are soft: once read here, the parent item can never disappear."""
        self.get_post(post_id)
        parent_path: str | None = None
        depth = 0
        if parent_id is not None:
            parent = self.get_comment(post_id, parent_id)
            parent_path = parent.path
            depth = parent.depth + 1

        comment_id = _new_ulid()
        now = _now_iso()
        comment = Comment(
            comment_id=comment_id,
            post_id=post_id,
            user_id=user_id,
            parent_id=parent_id,
            path=keys.child_path(parent_path, comment_id),
            depth=depth,
            content=content,
            created_at=now,
            updated_at=now,
        )
        self._table.put_item(
            Item={
                "PK": keys.post_pk(post_id),
                "SK": keys.comment_sk(comment.path),
                "GSI1PK": keys.user_gsi1pk(user_id),
                "GSI1SK": keys.comment_gsi1sk(now, comment_id),
                "GSI2PK": keys.comment_gsi2pk(post_id),
                "GSI2SK": keys.comment_gsi2sk(depth, comment.path),
                **comment.model_dump(),
            },
            ConditionExpression=Attr("PK").not_exists(),
        )
        return comment

    def get_comment(self, post_id: str, comment_id: str) -> Comment:
        """Access pattern #8, resolved by id rather than path: pages through
        the post's comment partition filtering on comment_id."""
        query: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(keys.post_pk(post_id))
            & Key("SK").begins_with(keys.COMMENT_SK_PREFIX),
            "FilterExpression": Attr("comment_id").eq(comment_id),
        }
        while True:
            result = self._table.query(**query)
            if result["Items"]:
                return _comment_from_item(result["Items"][0])
            lek = result.get("LastEvaluatedKey")
            if lek is None:
                raise CommentNotFoundError(comment_id)
            query["ExclusiveStartKey"] = lek

    def _paginated_comment_query(
        self,
        query: dict[str, Any],
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Comment], str | None]:
        start_key = _decode_cursor(cursor)
        if start_key is not None:
            query["ExclusiveStartKey"] = start_key

        if limit is not None:
            query["Limit"] = limit
            result = self._table.query(**query)
            items = [_comment_from_item(i) for i in result["Items"]]
            return items, _encode_cursor(result.get("LastEvaluatedKey"))

        items = []
        while True:
            result = self._table.query(**query)
            items.extend(_comment_from_item(i) for i in result["Items"])
            lek = result.get("LastEvaluatedKey")
            if lek is None:
                return items, None
            query["ExclusiveStartKey"] = lek

    def get_tree(
        self,
        post_id: str,
        max_depth: int | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Comment], str | None]:
        """Access pattern #2, in path (chronological) order.

        With max_depth (#6), the read runs against GSI2 where depth is a key
        condition — a range read with no post-filter amplification. Complete
        bounded reads are re-sorted into path order; *paginated* bounded pages
        arrive in GSI2SK (depth-major) order instead.
        """
        self.get_post(post_id)
        if max_depth is None:
            query: dict[str, Any] = {
                "KeyConditionExpression": Key("PK").eq(keys.post_pk(post_id))
                & Key("SK").begins_with(keys.COMMENT_SK_PREFIX),
            }
            return self._paginated_comment_query(query, limit, cursor)

        query = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(keys.comment_gsi2pk(post_id))
            & Key("GSI2SK").lte(keys.gsi2_max_depth_bound(max_depth)),
        }
        comments, next_cursor = self._paginated_comment_query(query, limit, cursor)
        if limit is None:
            comments.sort(key=lambda c: c.path)
        return comments, next_cursor

    def get_subtree(
        self,
        post_id: str,
        comment_id: str,
        max_depth: int | None = None,
        include_root: bool = True,
        direct_only: bool = False,
    ) -> list[Comment]:
        """Access patterns #4, #5 and #6 (subtree form), in path order.

        max_depth is absolute tree depth, as in CLAUDE.md pattern #6.
        direct_only=True returns only the immediate children (#5).

        Depth-bounded reads run one GSI2 query per level below the root
        (`begins_with(GSI2SK, "DEPTH#<level>#<root path>#")`), so they read
        exactly the returned comments — never the whole subtree.
        """
        root = self.get_comment(post_id, comment_id)
        if direct_only:
            max_depth = root.depth + 1
            include_root = False

        if max_depth is not None:
            comments = [root] if include_root and root.depth <= max_depth else []
            for depth in range(root.depth + 1, max_depth + 1):
                level_query: dict[str, Any] = {
                    "IndexName": "GSI2",
                    "KeyConditionExpression": Key("GSI2PK").eq(keys.comment_gsi2pk(post_id))
                    & Key("GSI2SK").begins_with(
                        keys.gsi2_descendant_level_prefix(depth, root.path)
                    ),
                }
                level, _ = self._paginated_comment_query(level_query)
                if not level:
                    # A tree level with no nodes has nothing below it.
                    break
                comments.extend(level)
            comments.sort(key=lambda c: c.path)
            return comments

        query: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq(keys.post_pk(post_id))
            & Key("SK").begins_with(keys.comment_sk(root.path)),
        }
        items, _ = self._paginated_comment_query(query)
        if not include_root:
            items = [c for c in items if c.comment_id != root.comment_id]
        return items

    def edit_comment(self, post_id: str, comment_id: str, user_id: str, content: str) -> Comment:
        """Access pattern #14."""
        comment = self.get_comment(post_id, comment_id)
        if comment.user_id != user_id:
            raise ForbiddenError(f"Comment {comment_id} does not belong to user {user_id}")
        now = _now_iso()
        try:
            self._table.update_item(
                Key={"PK": keys.post_pk(post_id), "SK": keys.comment_sk(comment.path)},
                UpdateExpression="SET content = :content, updated_at = :now",
                ConditionExpression=Attr("PK").exists() & Attr("deleted").eq(False),
                ExpressionAttributeValues={":content": content, ":now": now},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise CommentDeletedError(comment_id) from exc
            raise
        return comment.model_copy(update={"content": content, "updated_at": now})

    def delete_comment(self, post_id: str, comment_id: str, user_id: str) -> Comment:
        """Access pattern #13: soft delete. The item stays so child paths
        remain valid; content is cleared."""
        comment = self.get_comment(post_id, comment_id)
        if comment.user_id != user_id:
            raise ForbiddenError(f"Comment {comment_id} does not belong to user {user_id}")
        now = _now_iso()
        try:
            self._table.update_item(
                Key={"PK": keys.post_pk(post_id), "SK": keys.comment_sk(comment.path)},
                UpdateExpression="SET content = :empty, deleted = :true, updated_at = :now",
                ConditionExpression=Attr("PK").exists() & Attr("deleted").eq(False),
                ExpressionAttributeValues={":empty": "", ":true": True, ":now": now},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise CommentDeletedError(comment_id) from exc
            raise
        return comment.model_copy(update={"content": "", "deleted": True, "updated_at": now})

    def list_user_comments(
        self,
        user_id: str,
        since: str | None = None,
        post_id: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[list[Comment], str | None]:
        """Access patterns #9, #10 and #11 on GSI1, newest first.

        GSI1 is overloaded with vote items, so the sort-key condition is
        range-bounded to the TS# prefix rather than an open-ended '>'.
        """
        if since is not None:
            sk_condition = Key("GSI1SK").between(
                f"{keys.TS_PREFIX}{since}", f"{keys.TS_PREFIX}{keys.HIGH_SENTINEL}"
            )
        else:
            sk_condition = Key("GSI1SK").begins_with(keys.TS_PREFIX)
        query: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(keys.user_gsi1pk(user_id)) & sk_condition,
            "ScanIndexForward": False,
        }
        if post_id is not None:
            query["FilterExpression"] = Attr("post_id").eq(post_id)
        return self._paginated_comment_query(query, limit, cursor)

    # -- Votes ---------------------------------------------------------------

    def get_user_vote(self, post_id: str, user_id: str, comment_id: str) -> Vote | None:
        """Access pattern V4. Returns None when the user has not voted."""
        result = self._table.get_item(
            Key={"PK": keys.post_pk(post_id), "SK": keys.vote_sk(user_id, comment_id)}
        )
        item = result.get("Item")
        return _vote_from_item(item) if item is not None else None

    def list_user_votes_on_post(self, post_id: str, user_id: str) -> list[Vote]:
        """Access pattern V5: one user's votes across a whole post."""
        result = self._table.query(
            KeyConditionExpression=Key("PK").eq(keys.post_pk(post_id))
            & Key("SK").begins_with(keys.user_votes_sk_prefix(user_id))
        )
        return [_vote_from_item(i) for i in result["Items"]]

    def list_user_votes(self, user_id: str, value: int | None = None) -> list[Vote]:
        """Access pattern V6: a user's votes across all posts via GSI1."""
        query: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(keys.user_gsi1pk(user_id))
            & Key("GSI1SK").begins_with(keys.VOTE_PREFIX),
            "ScanIndexForward": False,
        }
        if value is not None:
            query["FilterExpression"] = Attr("value").eq(value)
        items = []
        while True:
            result = self._table.query(**query)
            items.extend(_vote_from_item(i) for i in result["Items"])
            lek = result.get("LastEvaluatedKey")
            if lek is None:
                return items
            query["ExclusiveStartKey"] = lek

    def cast_vote(self, post_id: str, comment_id: str, user_id: str, value: int) -> Comment:
        """Access pattern V1: read-then-transact with optimistic concurrency.

        Returns the comment with updated counters.
        """
        comment = self.get_comment(post_id, comment_id)
        if comment.deleted:
            raise CommentDeletedError(comment_id)
        prev_vote = self.get_user_vote(post_id, user_id, comment_id)
        prev = prev_vote.value if prev_vote is not None else None
        if prev == value:
            return comment

        now = _now_iso()
        created_at = prev_vote.created_at if prev_vote is not None else now
        vote_item = {
            "PK": keys.post_pk(post_id),
            "SK": keys.vote_sk(user_id, comment_id),
            "GSI1PK": keys.user_gsi1pk(user_id),
            "GSI1SK": keys.vote_gsi1sk(created_at, post_id, comment_id),
            "post_id": post_id,
            "comment_id": comment_id,
            "user_id": user_id,
            "value": value,
            "created_at": created_at,
            "updated_at": now,
        }
        put: dict[str, Any] = {
            "TableName": self._table_name,
            "Item": vote_item,
        }
        if prev is None:
            put["ConditionExpression"] = "attribute_not_exists(PK)"
        else:
            put["ConditionExpression"] = "#v = :prev"
            put["ExpressionAttributeNames"] = {"#v": "value"}
            put["ExpressionAttributeValues"] = {":prev": prev}
        self._transact_vote(comment, put_or_delete={"Put": put}, prev=prev, new=value)
        return self._reread_comment(comment)

    def remove_vote(self, post_id: str, comment_id: str, user_id: str) -> Comment:
        """Access pattern V2: delete the vote item + inverse counter delta."""
        comment = self.get_comment(post_id, comment_id)
        if comment.deleted:
            raise CommentDeletedError(comment_id)
        prev_vote = self.get_user_vote(post_id, user_id, comment_id)
        if prev_vote is None:
            raise VoteNotFoundError(comment_id)

        delete = {
            "TableName": self._table_name,
            "Key": {"PK": keys.post_pk(post_id), "SK": keys.vote_sk(user_id, comment_id)},
            "ConditionExpression": "#v = :prev",
            "ExpressionAttributeNames": {"#v": "value"},
            "ExpressionAttributeValues": {":prev": prev_vote.value},
        }
        self._transact_vote(
            comment, put_or_delete={"Delete": delete}, prev=prev_vote.value, new=None
        )
        return self._reread_comment(comment)

    def _transact_vote(
        self,
        comment: Comment,
        put_or_delete: dict[str, Any],
        prev: int | None,
        new: int | None,
    ) -> None:
        d_up, d_down, d_score = compute_vote_deltas(prev, new)
        update = {
            "TableName": self._table_name,
            "Key": {"PK": keys.post_pk(comment.post_id), "SK": keys.comment_sk(comment.path)},
            "UpdateExpression": "ADD upvotes :du, downvotes :dd, score :ds",
            "ConditionExpression": "attribute_exists(PK) AND deleted = :false",
            "ExpressionAttributeValues": {
                ":du": d_up,
                ":dd": d_down,
                ":ds": d_score,
                ":false": False,
            },
        }
        try:
            self._client.transact_write_items(TransactItems=[put_or_delete, {"Update": update}])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                raise VoteConflictError(comment.comment_id) from exc
            raise

    def _reread_comment(self, comment: Comment) -> Comment:
        result = self._table.get_item(
            Key={"PK": keys.post_pk(comment.post_id), "SK": keys.comment_sk(comment.path)}
        )
        return _comment_from_item(result["Item"])


_repository: CommentRepository | None = None


def get_repository() -> CommentRepository:
    """Lazy singleton used by the handlers; reset via reset_repository() in tests."""
    global _repository
    if _repository is None:
        _repository = CommentRepository(os.environ["TABLE_NAME"])
    return _repository


def reset_repository() -> None:
    global _repository
    _repository = None
