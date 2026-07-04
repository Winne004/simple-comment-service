"""Comment CRUD endpoints through the resolver."""

import time
from typing import Any


def create(client: Any, post_id: str, content: str, user: str, parent: str | None = None) -> Any:
    body: dict[str, Any] = {"content": content}
    if parent is not None:
        body["parent_id"] = parent
    status, comment = client.request("POST", f"/posts/{post_id}/comments", body=body, user=user)
    assert status == 201
    return comment


class TestCreateComment:
    def test_root(self, client: Any, post_id: str) -> None:
        comment = create(client, post_id, "hello", "alice")
        assert comment["depth"] == 0
        assert comment["parent_id"] is None
        assert comment["score"] == 0

    def test_reply(self, client: Any, post_id: str) -> None:
        root = create(client, post_id, "root", "alice")
        reply = create(client, post_id, "reply", "bob", parent=root["comment_id"])
        assert reply["depth"] == 1
        assert reply["parent_id"] == root["comment_id"]
        assert reply["path"].startswith(root["path"] + "#")

    def test_requires_user(self, client: Any, post_id: str) -> None:
        status, _ = client.request("POST", f"/posts/{post_id}/comments", body={"content": "x"})
        assert status == 401

    def test_missing_post_404(self, client: Any) -> None:
        status, body = client.request(
            "POST", "/posts/nope/comments", body={"content": "x"}, user="alice"
        )
        assert status == 404
        assert body["error"] == "post_not_found"

    def test_missing_parent_404(self, client: Any, post_id: str) -> None:
        status, body = client.request(
            "POST",
            f"/posts/{post_id}/comments",
            body={"content": "x", "parent_id": "nope"},
            user="alice",
        )
        assert status == 404
        assert body["error"] == "comment_not_found"

    def test_empty_content_rejected(self, client: Any, post_id: str) -> None:
        status, body = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": ""}, user="alice"
        )
        assert status == 400
        assert body["error"] == "validation_error"


class TestReadComment:
    def test_get_by_id(self, client: Any, post_id: str) -> None:
        comment = create(client, post_id, "hello", "alice")
        status, body = client.request("GET", f"/posts/{post_id}/comments/{comment['comment_id']}")
        assert status == 200
        assert body == comment

    def test_missing_404(self, client: Any, post_id: str) -> None:
        status, body = client.request("GET", f"/posts/{post_id}/comments/nope")
        assert status == 404
        assert body["error"] == "comment_not_found"

    def test_replies_subtree_and_direct(self, client: Any, post_id: str) -> None:
        root = create(client, post_id, "root", "alice")
        time.sleep(0.002)
        child = create(client, post_id, "child", "bob", parent=root["comment_id"])
        time.sleep(0.002)
        grandchild = create(client, post_id, "gc", "carol", parent=child["comment_id"])

        status, body = client.request(
            "GET", f"/posts/{post_id}/comments/{root['comment_id']}/replies"
        )
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [
            child["comment_id"],
            grandchild["comment_id"],
        ]

        status, body = client.request(
            "GET",
            f"/posts/{post_id}/comments/{root['comment_id']}/replies",
            query={"direct": "true"},
        )
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [child["comment_id"]]


class TestEditAndDelete:
    def test_edit(self, client: Any, post_id: str) -> None:
        comment = create(client, post_id, "before", "alice")
        status, body = client.request(
            "PATCH",
            f"/posts/{post_id}/comments/{comment['comment_id']}",
            body={"content": "after"},
            user="alice",
        )
        assert status == 200
        assert body["content"] == "after"

    def test_edit_wrong_user_403(self, client: Any, post_id: str) -> None:
        comment = create(client, post_id, "hi", "alice")
        status, body = client.request(
            "PATCH",
            f"/posts/{post_id}/comments/{comment['comment_id']}",
            body={"content": "hacked"},
            user="mallory",
        )
        assert status == 403
        assert body["error"] == "forbidden"

    def test_delete_then_edit_409(self, client: Any, post_id: str) -> None:
        comment = create(client, post_id, "hi", "alice")
        status, body = client.request(
            "DELETE", f"/posts/{post_id}/comments/{comment['comment_id']}", user="alice"
        )
        assert status == 200
        assert body["deleted"] is True
        assert body["content"] == ""

        status, body = client.request(
            "PATCH",
            f"/posts/{post_id}/comments/{comment['comment_id']}",
            body={"content": "again"},
            user="alice",
        )
        assert status == 409
        assert body["error"] == "comment_deleted"

    def test_delete_preserves_replies(self, client: Any, post_id: str) -> None:
        root = create(client, post_id, "root", "alice")
        reply = create(client, post_id, "reply", "bob", parent=root["comment_id"])
        client.request("DELETE", f"/posts/{post_id}/comments/{root['comment_id']}", user="alice")

        status, body = client.request("GET", f"/posts/{post_id}/comments")
        assert status == 200
        by_id = {c["comment_id"]: c for c in body["items"]}
        assert by_id[root["comment_id"]]["deleted"] is True
        assert by_id[reply["comment_id"]]["content"] == "reply"
