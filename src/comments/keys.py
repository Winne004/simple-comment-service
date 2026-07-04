"""Key and materialized-path construction for the single-table design.

All PK/SK/GSI values are built here and nowhere else. See CLAUDE.md for the
schema this implements.
"""

POST_META_SK = "META"
COMMENT_SK_PREFIX = "COMMENT#"
PATH_SEPARATOR = "#"
TS_PREFIX = "TS#"
VOTE_PREFIX = "VOTE#"
DEPTH_PREFIX = "DEPTH#"

# Depth is zero-padded inside GSI2SK so lexical sort matches numeric order.
MAX_KEYED_DEPTH = 9999

# ￿ sorts above any ASCII character, so "TS#<iso>" .. "TS#￿" bounds a
# range read to timestamp-keyed items without picking up "VOTE#..." rows on the
# overloaded GSI1.
HIGH_SENTINEL = "￿"


def post_pk(post_id: str) -> str:
    return f"POST#{post_id}"


def comment_sk(path: str) -> str:
    return f"{COMMENT_SK_PREFIX}{path}"


def child_path(parent_path: str | None, comment_id: str) -> str:
    """Materialized path for a new comment: parent's path plus its own ULID."""
    if parent_path is None:
        return comment_id
    return f"{parent_path}{PATH_SEPARATOR}{comment_id}"


def vote_sk(user_id: str, comment_id: str) -> str:
    return f"{VOTE_PREFIX}{user_id}#{comment_id}"


def user_votes_sk_prefix(user_id: str) -> str:
    """SK prefix matching all of one user's votes within a post partition."""
    return f"{VOTE_PREFIX}{user_id}#"


def user_gsi1pk(user_id: str) -> str:
    return f"USER#{user_id}"


def comment_gsi1sk(created_at: str, comment_id: str) -> str:
    return f"{TS_PREFIX}{created_at}#{comment_id}"


def vote_gsi1sk(created_at: str, post_id: str, comment_id: str) -> str:
    return f"{VOTE_PREFIX}{created_at}#{post_id}#{comment_id}"


def _padded_depth(depth: int) -> str:
    if not 0 <= depth <= MAX_KEYED_DEPTH:
        raise ValueError(f"depth {depth} outside keyed range 0..{MAX_KEYED_DEPTH}")
    return f"{depth:04d}"


def comment_gsi2pk(post_id: str) -> str:
    return post_pk(post_id)


def gsi2_depth_prefix(depth: int) -> str:
    """SK prefix matching all comments at exactly `depth` in a post."""
    return f"{DEPTH_PREFIX}{_padded_depth(depth)}#"


def comment_gsi2sk(depth: int, path: str) -> str:
    return f"{gsi2_depth_prefix(depth)}{path}"


def gsi2_descendant_level_prefix(depth: int, ancestor_path: str) -> str:
    """SK prefix matching descendants of `ancestor_path` at exactly `depth`."""
    return f"{gsi2_depth_prefix(depth)}{ancestor_path}{PATH_SEPARATOR}"


def gsi2_max_depth_bound(max_depth: int) -> str:
    """Upper bound for `GSI2SK <= …` range reads: everything at depth <= max_depth."""
    return f"{gsi2_depth_prefix(max_depth)}{HIGH_SENTINEL}"
