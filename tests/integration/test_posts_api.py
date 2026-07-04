"""Post endpoints through the resolver."""

import time
from typing import Any


class TestCreatePost:
    def test_created(self, client: Any) -> None:
        status, body = client.request("POST", "/posts", body={"title": "Hello"}, user="alice")
        assert status == 201
        assert body["title"] == "Hello"
        assert body["post_id"]

    def test_requires_user_header(self, client: Any) -> None:
        status, _ = client.request("POST", "/posts", body={"title": "Hello"})
        assert status == 401

    def test_empty_title_rejected(self, client: Any) -> None:
        status, body = client.request("POST", "/posts", body={"title": ""}, user="alice")
        assert status == 400
        assert body["error"] == "validation_error"

    def test_invalid_json_rejected(self, client: Any) -> None:
        status, body = client.request("POST", "/posts", user="alice", raw_body="{nope")
        assert status == 400
        assert body["error"] == "invalid_json"


class TestGetPost:
    def test_roundtrip(self, client: Any, post_id: str) -> None:
        status, body = client.request("GET", f"/posts/{post_id}")
        assert status == 200
        assert body["post_id"] == post_id

    def test_missing_post_404(self, client: Any) -> None:
        status, body = client.request("GET", "/posts/nope")
        assert status == 404
        assert body["error"] == "post_not_found"

    def test_unknown_route_404(self, client: Any) -> None:
        status, _ = client.request("GET", "/bogus")
        assert status == 404


class TestGetTree:
    def test_tree_and_sort_top(self, client: Any, post_id: str) -> None:
        _, first = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "first"}, user="alice"
        )
        time.sleep(0.002)
        _, second = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "second"}, user="bob"
        )
        client.request(
            "PUT",
            f"/posts/{post_id}/comments/{second['comment_id']}/vote",
            body={"value": 1},
            user="carol",
        )

        status, body = client.request("GET", f"/posts/{post_id}/comments")
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [
            first["comment_id"],
            second["comment_id"],
        ]

        status, body = client.request("GET", f"/posts/{post_id}/comments", query={"sort": "top"})
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [
            second["comment_id"],
            first["comment_id"],
        ]

    def test_max_depth(self, client: Any, post_id: str) -> None:
        _, root = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "root"}, user="alice"
        )
        client.request(
            "POST",
            f"/posts/{post_id}/comments",
            body={"content": "reply", "parent_id": root["comment_id"]},
            user="bob",
        )
        status, body = client.request("GET", f"/posts/{post_id}/comments", query={"max_depth": "0"})
        assert status == 200
        assert [c["comment_id"] for c in body["items"]] == [root["comment_id"]]

    def test_pagination_cursor(self, client: Any, post_id: str) -> None:
        for i in range(3):
            client.request(
                "POST", f"/posts/{post_id}/comments", body={"content": f"c{i}"}, user="alice"
            )
            time.sleep(0.002)
        status, page = client.request("GET", f"/posts/{post_id}/comments", query={"limit": "2"})
        assert status == 200
        assert len(page["items"]) == 2
        assert page["next_cursor"] is not None

        status, rest = client.request(
            "GET",
            f"/posts/{post_id}/comments",
            query={"limit": "2", "cursor": page["next_cursor"]},
        )
        assert status == 200
        seen = {c["comment_id"] for c in page["items"]} | {c["comment_id"] for c in rest["items"]}
        assert len(seen) == 3

    def test_bad_query_params_rejected(self, client: Any, post_id: str) -> None:
        for query in (
            {"max_depth": "x"},
            {"max_depth": "-1"},
            {"max_depth": "10000"},
            {"limit": "x"},
            {"limit": "0"},
            {"sort": "bogus"},
            {"cursor": "!!!"},
        ):
            status, _ = client.request("GET", f"/posts/{post_id}/comments", query=query)
            assert status == 400, query
