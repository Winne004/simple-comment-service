"""Vote endpoints through the resolver."""

from typing import Any

import pytest


@pytest.fixture
def comment_id(client: Any, post_id: str) -> str:
    status, comment = client.request(
        "POST", f"/posts/{post_id}/comments", body={"content": "target"}, user="author"
    )
    assert status == 201
    return comment["comment_id"]


class TestCastVote:
    def test_upvote(self, client: Any, post_id: str, comment_id: str) -> None:
        status, body = client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 1},
            user="alice",
        )
        assert status == 200
        assert (body["upvotes"], body["downvotes"], body["score"]) == (1, 0, 1)

    def test_change_vote(self, client: Any, post_id: str, comment_id: str) -> None:
        vote_path = f"/posts/{post_id}/comments/{comment_id}/vote"
        client.request("PUT", vote_path, body={"value": 1}, user="alice")
        status, body = client.request("PUT", vote_path, body={"value": -1}, user="alice")
        assert status == 200
        assert (body["upvotes"], body["downvotes"], body["score"]) == (0, 1, -1)

    def test_invalid_value_rejected(self, client: Any, post_id: str, comment_id: str) -> None:
        status, body = client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 0},
            user="alice",
        )
        assert status == 400
        assert body["error"] == "validation_error"

    def test_requires_user(self, client: Any, post_id: str, comment_id: str) -> None:
        status, _ = client.request(
            "PUT", f"/posts/{post_id}/comments/{comment_id}/vote", body={"value": 1}
        )
        assert status == 401

    def test_vote_on_deleted_comment_409(self, client: Any, post_id: str, comment_id: str) -> None:
        client.request("DELETE", f"/posts/{post_id}/comments/{comment_id}", user="author")
        status, body = client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 1},
            user="alice",
        )
        assert status == 409
        assert body["error"] == "comment_deleted"


class TestRemoveAndReadVotes:
    def test_remove_vote(self, client: Any, post_id: str, comment_id: str) -> None:
        vote_path = f"/posts/{post_id}/comments/{comment_id}/vote"
        client.request("PUT", vote_path, body={"value": 1}, user="alice")
        status, body = client.request("DELETE", vote_path, user="alice")
        assert status == 200
        assert (body["upvotes"], body["downvotes"], body["score"]) == (0, 0, 0)

    def test_remove_without_vote_404(self, client: Any, post_id: str, comment_id: str) -> None:
        status, body = client.request(
            "DELETE", f"/posts/{post_id}/comments/{comment_id}/vote", user="alice"
        )
        assert status == 404
        assert body["error"] == "vote_not_found"

    def test_get_own_vote(self, client: Any, post_id: str, comment_id: str) -> None:
        vote_path = f"/posts/{post_id}/comments/{comment_id}/vote"
        status, body = client.request("GET", vote_path, user="alice")
        assert status == 404

        client.request("PUT", vote_path, body={"value": -1}, user="alice")
        status, body = client.request("GET", vote_path, user="alice")
        assert status == 200
        assert body["value"] == -1

    def test_list_votes_on_post(self, client: Any, post_id: str, comment_id: str) -> None:
        _, other = client.request(
            "POST", f"/posts/{post_id}/comments", body={"content": "other"}, user="author"
        )
        client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 1},
            user="alice",
        )
        client.request(
            "PUT",
            f"/posts/{post_id}/comments/{other['comment_id']}/vote",
            body={"value": -1},
            user="alice",
        )
        client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 1},
            user="bob",
        )

        status, body = client.request("GET", f"/posts/{post_id}/votes", user="alice")
        assert status == 200
        assert {(v["comment_id"], v["value"]) for v in body["items"]} == {
            (comment_id, 1),
            (other["comment_id"], -1),
        }

    def test_list_user_votes_across_posts(self, client: Any, post_id: str, comment_id: str) -> None:
        client.request(
            "PUT",
            f"/posts/{post_id}/comments/{comment_id}/vote",
            body={"value": 1},
            user="alice",
        )
        status, body = client.request("GET", "/users/alice/votes")
        assert status == 200
        assert [(v["comment_id"], v["value"]) for v in body["items"]] == [(comment_id, 1)]

        status, body = client.request("GET", "/users/alice/votes", query={"value": "-1"})
        assert status == 200
        assert body["items"] == []

        status, _ = client.request("GET", "/users/alice/votes", query={"value": "2"})
        assert status == 400
