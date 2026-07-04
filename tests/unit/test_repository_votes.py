"""Voting: delta matrix, invariants, and the transactional write path."""

import time
from typing import Any

import pytest

from comments.errors import (
    CommentDeletedError,
    VoteConflictError,
    VoteNotFoundError,
)
from comments.repository import CommentRepository, compute_vote_deltas


@pytest.fixture
def post_and_comment(repo: CommentRepository) -> tuple[str, str]:
    post_id = repo.create_post("A post").post_id
    comment = repo.create_comment(post_id, "author", "hello")
    return post_id, comment.comment_id


def counters(repo: CommentRepository, post_id: str, comment_id: str) -> tuple[int, int, int]:
    c = repo.get_comment(post_id, comment_id)
    return c.upvotes, c.downvotes, c.score


@pytest.mark.parametrize(
    ("prev", "new", "expected"),
    [
        (None, 1, (1, 0, 1)),
        (None, -1, (0, 1, -1)),
        (1, -1, (-1, 1, -2)),
        (-1, 1, (1, -1, 2)),
        (1, None, (-1, 0, -1)),
        (-1, None, (0, -1, 1)),
        (1, 1, (0, 0, 0)),
        (-1, -1, (0, 0, 0)),
        (None, None, (0, 0, 0)),
    ],
)
def test_compute_vote_deltas(
    prev: int | None, new: int | None, expected: tuple[int, int, int]
) -> None:
    assert compute_vote_deltas(prev, new) == expected


class TestCastVote:
    def test_upvote_updates_counters_and_writes_vote_item(
        self, repo: CommentRepository, comments_table: Any, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        updated = repo.cast_vote(post_id, comment_id, "alice", 1)
        assert (updated.upvotes, updated.downvotes, updated.score) == (1, 0, 1)

        item = comments_table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": f"VOTE#alice#{comment_id}"}
        )["Item"]
        assert item["value"] == 1
        assert item["GSI1PK"] == "USER#alice"
        assert item["GSI1SK"] == f"VOTE#{item['created_at']}#{post_id}#{comment_id}"

    def test_downvote(self, repo: CommentRepository, post_and_comment: tuple[str, str]) -> None:
        post_id, comment_id = post_and_comment
        updated = repo.cast_vote(post_id, comment_id, "alice", -1)
        assert (updated.upvotes, updated.downvotes, updated.score) == (0, 1, -1)

    def test_change_up_to_down(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        updated = repo.cast_vote(post_id, comment_id, "alice", -1)
        assert (updated.upvotes, updated.downvotes, updated.score) == (0, 1, -1)

    def test_change_down_to_up(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", -1)
        updated = repo.cast_vote(post_id, comment_id, "alice", 1)
        assert (updated.upvotes, updated.downvotes, updated.score) == (1, 0, 1)

    def test_same_vote_is_a_noop(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        updated = repo.cast_vote(post_id, comment_id, "alice", 1)
        assert (updated.upvotes, updated.downvotes, updated.score) == (1, 0, 1)

    def test_one_vote_per_user_and_comment(
        self, repo: CommentRepository, comments_table: Any, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        repo.cast_vote(post_id, comment_id, "alice", -1)
        repo.cast_vote(post_id, comment_id, "alice", 1)
        assert counters(repo, post_id, comment_id) == (1, 0, 1)

        votes = comments_table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": f"POST#{post_id}", ":sk": "VOTE#alice#"},
        )["Items"]
        assert len(votes) == 1

    def test_votes_from_multiple_users_accumulate(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        repo.cast_vote(post_id, comment_id, "bob", 1)
        repo.cast_vote(post_id, comment_id, "carol", -1)
        assert counters(repo, post_id, comment_id) == (2, 1, 1)

    def test_vote_on_deleted_comment_rejected(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.delete_comment(post_id, comment_id, "author")
        with pytest.raises(CommentDeletedError):
            repo.cast_vote(post_id, comment_id, "alice", 1)

    def test_concurrent_vote_fails_condition_check(
        self,
        repo: CommentRepository,
        post_and_comment: tuple[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulate a race: another request wrote a vote between our read and
        # the transaction, so the Put's ConditionExpression must fail.
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        monkeypatch.setattr(repo, "get_user_vote", lambda *args, **kwargs: None)
        with pytest.raises(VoteConflictError):
            repo.cast_vote(post_id, comment_id, "alice", -1)
        # Counters were not corrupted by the failed transaction.
        monkeypatch.undo()
        assert counters(repo, post_id, comment_id) == (1, 0, 1)


class TestRemoveVote:
    def test_remove_restores_counters_and_deletes_item(
        self, repo: CommentRepository, comments_table: Any, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", -1)
        updated = repo.remove_vote(post_id, comment_id, "alice")
        assert (updated.upvotes, updated.downvotes, updated.score) == (0, 0, 0)

        result = comments_table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": f"VOTE#alice#{comment_id}"}
        )
        assert "Item" not in result

    def test_remove_without_vote_raises(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        with pytest.raises(VoteNotFoundError):
            repo.remove_vote(post_id, comment_id, "alice")


class TestVoteReads:
    def test_get_user_vote(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        assert repo.get_user_vote(post_id, "alice", comment_id) is None
        repo.cast_vote(post_id, comment_id, "alice", 1)
        vote = repo.get_user_vote(post_id, "alice", comment_id)
        assert vote is not None
        assert vote.value == 1
        assert vote.user_id == "alice"

    def test_vote_change_preserves_created_at(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        repo.cast_vote(post_id, comment_id, "alice", 1)
        original = repo.get_user_vote(post_id, "alice", comment_id)
        assert original is not None
        time.sleep(0.002)
        repo.cast_vote(post_id, comment_id, "alice", -1)
        changed = repo.get_user_vote(post_id, "alice", comment_id)
        assert changed is not None
        assert changed.created_at == original.created_at
        assert changed.updated_at > original.updated_at

    def test_list_user_votes_on_post_only_that_user(
        self, repo: CommentRepository, post_and_comment: tuple[str, str]
    ) -> None:
        post_id, comment_id = post_and_comment
        other = repo.create_comment(post_id, "author", "another")
        repo.cast_vote(post_id, comment_id, "alice", 1)
        repo.cast_vote(post_id, other.comment_id, "alice", -1)
        repo.cast_vote(post_id, comment_id, "bob", 1)

        votes = repo.list_user_votes_on_post(post_id, "alice")
        assert {(v.comment_id, v.value) for v in votes} == {
            (comment_id, 1),
            (other.comment_id, -1),
        }

    def test_list_user_votes_across_posts(self, repo: CommentRepository) -> None:
        post_a = repo.create_post("a").post_id
        post_b = repo.create_post("b").post_id
        comment_a = repo.create_comment(post_a, "author", "in a")
        comment_b = repo.create_comment(post_b, "author", "in b")
        repo.cast_vote(post_a, comment_a.comment_id, "alice", 1)
        repo.cast_vote(post_b, comment_b.comment_id, "alice", -1)

        votes = repo.list_user_votes("alice")
        assert {(v.post_id, v.value) for v in votes} == {(post_a, 1), (post_b, -1)}

        upvoted = repo.list_user_votes("alice", value=1)
        assert [(v.post_id, v.value) for v in upvoted] == [(post_a, 1)]

    def test_comments_do_not_leak_into_vote_listing(self, repo: CommentRepository) -> None:
        # The overloaded GSI1 also holds alice's comments; the VOTE# prefix
        # condition must exclude them.
        post_id = repo.create_post("a").post_id
        target = repo.create_comment(post_id, "author", "target")
        repo.create_comment(post_id, "alice", "alice writes too")
        repo.cast_vote(post_id, target.comment_id, "alice", 1)

        votes = repo.list_user_votes("alice")
        assert [v.comment_id for v in votes] == [target.comment_id]
