"""Key/path construction, asserted against the documented schema."""

from comments import keys


def test_post_pk() -> None:
    assert keys.post_pk("p1") == "POST#p1"


def test_post_meta_sk() -> None:
    assert keys.POST_META_SK == "META"


def test_comment_sk_from_path() -> None:
    assert keys.comment_sk("aaa#bbb#ccc") == "COMMENT#aaa#bbb#ccc"


def test_child_path_root() -> None:
    assert keys.child_path(None, "aaa") == "aaa"


def test_child_path_nested() -> None:
    assert keys.child_path("aaa#bbb", "ccc") == "aaa#bbb#ccc"


def test_vote_sk_user_before_comment() -> None:
    assert keys.vote_sk("u1", "c1") == "VOTE#u1#c1"


def test_user_votes_sk_prefix() -> None:
    assert keys.user_votes_sk_prefix("u1") == "VOTE#u1#"
    assert keys.vote_sk("u1", "c1").startswith(keys.user_votes_sk_prefix("u1"))


def test_user_gsi1pk() -> None:
    assert keys.user_gsi1pk("u1") == "USER#u1"


def test_comment_gsi1sk() -> None:
    assert keys.comment_gsi1sk("2026-01-01T00:00:00+00:00", "c1") == (
        "TS#2026-01-01T00:00:00+00:00#c1"
    )


def test_vote_gsi1sk() -> None:
    assert keys.vote_gsi1sk("2026-01-01T00:00:00+00:00", "p1", "c1") == (
        "VOTE#2026-01-01T00:00:00+00:00#p1#c1"
    )


def test_high_sentinel_sorts_above_ascii() -> None:
    assert f"TS#{keys.HIGH_SENTINEL}" > "TS#2026-12-31"
    assert f"TS#{keys.HIGH_SENTINEL}" > "TS#zzzz"


def test_comment_gsi2pk_matches_post_partition() -> None:
    assert keys.comment_gsi2pk("p1") == keys.post_pk("p1")


def test_comment_gsi2sk_zero_pads_depth() -> None:
    assert keys.comment_gsi2sk(0, "aaa") == "DEPTH#0000#aaa"
    assert keys.comment_gsi2sk(3, "aaa#bbb") == "DEPTH#0003#aaa#bbb"


def test_gsi2_depth_prefix_matches_exact_level() -> None:
    assert keys.gsi2_depth_prefix(2) == "DEPTH#0002#"
    assert keys.comment_gsi2sk(2, "a#b#c").startswith(keys.gsi2_depth_prefix(2))


def test_gsi2_descendant_level_prefix() -> None:
    prefix = keys.gsi2_descendant_level_prefix(1, "aaa")
    assert prefix == "DEPTH#0001#aaa#"
    assert keys.comment_gsi2sk(1, "aaa#bbb").startswith(prefix)
    # A sibling subtree never matches.
    assert not keys.comment_gsi2sk(1, "zzz#bbb").startswith(prefix)


def test_gsi2_max_depth_bound_brackets_levels() -> None:
    bound = keys.gsi2_max_depth_bound(2)
    assert keys.comment_gsi2sk(2, "any#path#here") < bound
    assert keys.comment_gsi2sk(0, "any") < bound
    assert keys.comment_gsi2sk(3, "any#path#here#deeper") > bound


def test_padded_depth_zero_padding_keeps_lexical_order() -> None:
    assert keys.gsi2_depth_prefix(9) < keys.gsi2_depth_prefix(10) < keys.gsi2_depth_prefix(100)


def test_depth_outside_keyed_range_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        keys.gsi2_depth_prefix(-1)
    with pytest.raises(ValueError):
        keys.gsi2_depth_prefix(keys.MAX_KEYED_DEPTH + 1)
