"""Repository tests for posts and the comment tree, asserting on real keys."""

import time
from typing import Any

import pytest

from comments.errors import (
    CommentDeletedError,
    CommentNotFoundError,
    ForbiddenError,
    InvalidCursorError,
    PostNotFoundError,
)
from comments.models import Comment
from comments.repository import CommentRepository


def make_post(repo: CommentRepository) -> str:
    return repo.create_post("A post").post_id


def make_thread(repo: CommentRepository, post_id: str) -> tuple[Comment, Comment, Comment]:
    """root -> child -> grandchild; tiny sleeps keep ULID sibling order stable."""
    root = repo.create_comment(post_id, "alice", "root")
    time.sleep(0.002)
    child = repo.create_comment(post_id, "bob", "child", parent_id=root.comment_id)
    time.sleep(0.002)
    grandchild = repo.create_comment(post_id, "carol", "grandchild", parent_id=child.comment_id)
    return root, child, grandchild


class TestPosts:
    def test_create_and_get_roundtrip(self, repo: CommentRepository) -> None:
        post = repo.create_post("Hello")
        fetched = repo.get_post(post.post_id)
        assert fetched == post

    def test_post_item_keys(self, repo: CommentRepository, comments_table: Any) -> None:
        post = repo.create_post("Hello")
        item = comments_table.get_item(Key={"PK": f"POST#{post.post_id}", "SK": "META"})["Item"]
        assert item["title"] == "Hello"

    def test_get_missing_post_raises(self, repo: CommentRepository) -> None:
        with pytest.raises(PostNotFoundError):
            repo.get_post("nope")


class TestCreateComment:
    def test_root_comment_keys_and_attrs(
        self, repo: CommentRepository, comments_table: Any
    ) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "hi")

        assert comment.depth == 0
        assert comment.parent_id is None
        assert comment.path == comment.comment_id

        item = comments_table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": f"COMMENT#{comment.comment_id}"}
        )["Item"]
        assert item["GSI1PK"] == "USER#alice"
        assert item["GSI1SK"] == f"TS#{comment.created_at}#{comment.comment_id}"
        assert item["GSI2PK"] == f"POST#{post_id}"
        assert item["GSI2SK"] == f"DEPTH#0000#{comment.path}"
        assert item["depth"] == 0
        assert item["deleted"] is False
        assert item["upvotes"] == 0 and item["downvotes"] == 0 and item["score"] == 0

    def test_reply_extends_parent_path(self, repo: CommentRepository, comments_table: Any) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)

        assert child.path == f"{root.path}#{child.comment_id}"
        assert child.depth == 1
        assert child.parent_id == root.comment_id
        assert grandchild.path == f"{root.path}#{child.comment_id}#{grandchild.comment_id}"
        assert grandchild.depth == 2

        item = comments_table.get_item(
            Key={"PK": f"POST#{post_id}", "SK": f"COMMENT#{grandchild.path}"}
        )["Item"]
        assert item["comment_id"] == grandchild.comment_id
        assert item["GSI2SK"] == f"DEPTH#0002#{grandchild.path}"

    def test_comment_on_missing_post_raises(self, repo: CommentRepository) -> None:
        with pytest.raises(PostNotFoundError):
            repo.create_comment("nope", "alice", "hi")

    def test_reply_to_missing_parent_raises(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        with pytest.raises(CommentNotFoundError):
            repo.create_comment(post_id, "alice", "hi", parent_id="nope")


class TestTreeReads:
    def test_get_tree_returns_all_in_path_order(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)
        time.sleep(0.002)
        second_root = repo.create_comment(post_id, "dave", "second root")

        tree, cursor = repo.get_tree(post_id)
        assert cursor is None
        assert [c.comment_id for c in tree] == [
            root.comment_id,
            child.comment_id,
            grandchild.comment_id,
            second_root.comment_id,
        ]

    def test_get_tree_missing_post_raises(self, repo: CommentRepository) -> None:
        with pytest.raises(PostNotFoundError):
            repo.get_tree("nope")

    def test_get_tree_max_depth(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)

        bounded, _ = repo.get_tree(post_id, max_depth=1)
        assert {c.comment_id for c in bounded} == {root.comment_id, child.comment_id}

        roots_only, _ = repo.get_tree(post_id, max_depth=0)
        assert [c.comment_id for c in roots_only] == [root.comment_id]

    def test_get_subtree_node_and_descendants(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)
        repo.create_comment(post_id, "dave", "unrelated root")

        subtree = repo.get_subtree(post_id, child.comment_id)
        assert [c.comment_id for c in subtree] == [child.comment_id, grandchild.comment_id]

    def test_get_subtree_excluding_root(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)

        descendants = repo.get_subtree(post_id, root.comment_id, include_root=False)
        assert [c.comment_id for c in descendants] == [child.comment_id, grandchild.comment_id]

    def test_get_subtree_direct_children_only(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)
        time.sleep(0.002)
        second_child = repo.create_comment(post_id, "dave", "c2", parent_id=root.comment_id)

        children = repo.get_subtree(post_id, root.comment_id, direct_only=True)
        assert [c.comment_id for c in children] == [child.comment_id, second_child.comment_id]

    def test_get_subtree_max_depth_is_absolute(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)

        subtree = repo.get_subtree(post_id, root.comment_id, max_depth=1)
        assert {c.comment_id for c in subtree} == {root.comment_id, child.comment_id}

    def test_get_comment_by_id(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        _, child, _ = make_thread(repo, post_id)
        assert repo.get_comment(post_id, child.comment_id) == child

    def test_get_missing_comment_raises(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        with pytest.raises(CommentNotFoundError):
            repo.get_comment(post_id, "nope")

    def test_tree_pagination_via_cursor(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        created = []
        for i in range(5):
            created.append(repo.create_comment(post_id, "alice", f"c{i}"))
            time.sleep(0.002)

        collected: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            page, cursor = repo.get_tree(post_id, limit=2, cursor=cursor)
            collected.extend(c.comment_id for c in page)
            pages += 1
            if cursor is None:
                break
        assert collected == [c.comment_id for c in created]
        assert pages >= 3

    def test_invalid_cursor_raises(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        with pytest.raises(InvalidCursorError):
            repo.get_tree(post_id, cursor="not-a-cursor")
        with pytest.raises(InvalidCursorError):
            repo.get_tree(post_id, cursor="bm90LWEtZGljdA==")  # b64 of 'not-a-dict'


class TestDepthReadsViaGsi2:
    def test_bounded_tree_read_paginates(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, _grandchild = make_thread(repo, post_id)
        time.sleep(0.002)
        second_root = repo.create_comment(post_id, "dave", "second root")

        collected: list[str] = []
        cursor: str | None = None
        while True:
            page, cursor = repo.get_tree(post_id, max_depth=1, limit=2, cursor=cursor)
            collected.extend(c.comment_id for c in page)
            if cursor is None:
                break
        # Grandchild (depth 2) excluded; pages arrive in depth-major order.
        assert collected == [root.comment_id, second_root.comment_id, child.comment_id]

    def test_gsi2_contains_only_comments(
        self, repo: CommentRepository, comments_table: Any
    ) -> None:
        # GSI2 is sparse: post META and vote items never set GSI2 keys, so a
        # depth-bounded read can never pay for them.
        post_id = make_post(repo)
        comment = repo.create_comment(repo.get_post(post_id).post_id, "alice", "hi")
        repo.cast_vote(post_id, comment.comment_id, "bob", 1)

        from boto3.dynamodb.conditions import Key

        items = comments_table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"POST#{post_id}"),
        )["Items"]
        assert [i["SK"] for i in items] == [f"COMMENT#{comment.path}"]

    def test_subtree_max_depth_below_root_is_empty(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        _root, child, _grandchild = make_thread(repo, post_id)
        assert repo.get_subtree(post_id, child.comment_id, max_depth=0) == []

    def test_bounded_subtree_stops_at_first_empty_level(self, repo: CommentRepository) -> None:
        # max_depth far beyond the real tree depth must not degrade into one
        # query per requested level: an empty level ends the walk.
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)
        subtree = repo.get_subtree(post_id, root.comment_id, max_depth=50)
        assert [c.comment_id for c in subtree] == [
            root.comment_id,
            child.comment_id,
            grandchild.comment_id,
        ]

    def test_direct_children_of_deep_parent(self, repo: CommentRepository) -> None:
        # Children query must not match the parent's siblings or their
        # subtrees, only descendants one level down.
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)
        time.sleep(0.002)
        sibling = repo.create_comment(post_id, "dave", "sibling", parent_id=root.comment_id)
        time.sleep(0.002)
        repo.create_comment(post_id, "erin", "nephew", parent_id=sibling.comment_id)

        children = repo.get_subtree(post_id, child.comment_id, direct_only=True)
        assert [c.comment_id for c in children] == [grandchild.comment_id]


class TestEditAndDelete:
    def test_edit_updates_content_and_timestamp(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "before")
        edited = repo.edit_comment(post_id, comment.comment_id, "alice", "after")
        assert edited.content == "after"

        fetched = repo.get_comment(post_id, comment.comment_id)
        assert fetched.content == "after"
        assert fetched.updated_at >= fetched.created_at

    def test_edit_by_other_user_forbidden(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "hi")
        with pytest.raises(ForbiddenError):
            repo.edit_comment(post_id, comment.comment_id, "mallory", "hacked")

    def test_edit_deleted_comment_raises(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "hi")
        repo.delete_comment(post_id, comment.comment_id, "alice")
        with pytest.raises(CommentDeletedError):
            repo.edit_comment(post_id, comment.comment_id, "alice", "again")

    def test_soft_delete_preserves_children(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        root, child, grandchild = make_thread(repo, post_id)

        deleted = repo.delete_comment(post_id, child.comment_id, "bob")
        assert deleted.deleted is True
        assert deleted.content == ""

        # The tombstone stays in place and the whole subtree is still readable.
        tree, _ = repo.get_tree(post_id)
        assert [c.comment_id for c in tree] == [
            root.comment_id,
            child.comment_id,
            grandchild.comment_id,
        ]
        tombstone = next(c for c in tree if c.comment_id == child.comment_id)
        assert tombstone.deleted is True and tombstone.content == ""
        surviving = next(c for c in tree if c.comment_id == grandchild.comment_id)
        assert surviving.deleted is False and surviving.content == "grandchild"

    def test_delete_twice_raises(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "hi")
        repo.delete_comment(post_id, comment.comment_id, "alice")
        with pytest.raises(CommentDeletedError):
            repo.delete_comment(post_id, comment.comment_id, "alice")

    def test_delete_by_other_user_forbidden(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        comment = repo.create_comment(post_id, "alice", "hi")
        with pytest.raises(ForbiddenError):
            repo.delete_comment(post_id, comment.comment_id, "mallory")


class TestUserComments:
    def test_lists_across_posts_newest_first(self, repo: CommentRepository) -> None:
        post_a = make_post(repo)
        post_b = make_post(repo)
        first = repo.create_comment(post_a, "alice", "first")
        time.sleep(0.002)
        second = repo.create_comment(post_b, "alice", "second")
        repo.create_comment(post_a, "bob", "not alice")

        items, cursor = repo.list_user_comments("alice")
        assert cursor is None
        assert [c.comment_id for c in items] == [second.comment_id, first.comment_id]

    def test_votes_do_not_leak_into_user_comments(self, repo: CommentRepository) -> None:
        # GSI1 is overloaded with vote items; the TS#-bounded key condition
        # must keep them out of comment listings.
        post_id = make_post(repo)
        target = repo.create_comment(post_id, "bob", "target")
        mine = repo.create_comment(post_id, "alice", "mine")
        repo.cast_vote(post_id, target.comment_id, "alice", 1)

        items, _ = repo.list_user_comments("alice")
        assert [c.comment_id for c in items] == [mine.comment_id]

        items_since, _ = repo.list_user_comments("alice", since="2000-01-01T00:00:00+00:00")
        assert [c.comment_id for c in items_since] == [mine.comment_id]

    def test_since_filters_older_comments(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        old = repo.create_comment(post_id, "alice", "old")
        time.sleep(0.002)
        new = repo.create_comment(post_id, "alice", "new")

        items, _ = repo.list_user_comments("alice", since=new.created_at)
        assert [c.comment_id for c in items] == [new.comment_id]
        assert old.comment_id not in {c.comment_id for c in items}

    def test_post_id_filter(self, repo: CommentRepository) -> None:
        post_a = make_post(repo)
        post_b = make_post(repo)
        in_a = repo.create_comment(post_a, "alice", "in a")
        repo.create_comment(post_b, "alice", "in b")

        items, _ = repo.list_user_comments("alice", post_id=post_a)
        assert [c.comment_id for c in items] == [in_a.comment_id]

    def test_pagination(self, repo: CommentRepository) -> None:
        post_id = make_post(repo)
        for i in range(3):
            repo.create_comment(post_id, "alice", f"c{i}")
            time.sleep(0.002)

        page, cursor = repo.list_user_comments("alice", limit=2)
        assert len(page) == 2
        assert cursor is not None
        rest, cursor = repo.list_user_comments("alice", limit=2, cursor=cursor)
        assert len(rest) == 1
        all_ids = {c.comment_id for c in page} | {c.comment_id for c in rest}
        assert len(all_ids) == 3
