"""User comment listing (GSI1) through the resolver."""

import time
from typing import Any


class TestListUserComments:
    def test_across_posts_newest_first(self, client: Any) -> None:
        _, post_a = client.request("POST", "/posts", body={"title": "a"}, user="op")
        _, post_b = client.request("POST", "/posts", body={"title": "b"}, user="op")
        _, first = client.request(
            "POST", f"/posts/{post_a['post_id']}/comments", body={"content": "1"}, user="alice"
        )
        time.sleep(0.002)
        _, second = client.request(
            "POST", f"/posts/{post_b['post_id']}/comments", body={"content": "2"}, user="alice"
        )

        status, body = client.request("GET", "/users/alice/comments")
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [
            second["comment_id"],
            first["comment_id"],
        ]

    def test_since_and_post_filter(self, client: Any, post_id: str) -> None:
        _, old = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "old"}, user="alice"
        )
        time.sleep(0.002)
        _, new = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "new"}, user="alice"
        )

        status, body = client.request(
            "GET", "/users/alice/comments", query={"since": new["created_at"]}
        )
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [new["comment_id"]]

        status, body = client.request(
            "GET", "/users/alice/comments", query={"post_id": "different-post"}
        )
        assert status == 200
        assert body["items"] == []

    def test_pagination(self, client: Any, post_id: str) -> None:
        for i in range(3):
            client.request(
                "POST", f"/posts/{post_id}/comments", body={"content": f"c{i}"}, user="alice"
            )
            time.sleep(0.002)

        status, page = client.request("GET", "/users/alice/comments", query={"limit": "2"})
        assert status == 200
        assert len(page["items"]) == 2
        assert page["next_cursor"] is not None

        status, rest = client.request(
            "GET",
            "/users/alice/comments",
            query={"limit": "2", "cursor": page["next_cursor"]},
        )
        assert status == 200
        ids = {c["comment_id"] for c in page["items"]} | {c["comment_id"] for c in rest["items"]}
        assert len(ids) == 3

    def test_empty_for_unknown_user(self, client: Any) -> None:
        status, body = client.request("GET", "/users/nobody/comments")
        assert status == 200
        assert body["items"] == []
        assert body["next_cursor"] is None
