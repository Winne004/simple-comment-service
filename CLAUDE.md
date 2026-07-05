# CLAUDE.md

Guidance for working in this repository.

## Project overview

`simple-comment-service` is a serverless comment API. Users post comments on
subjects ("posts"), and comments can reply to other comments, forming a **tree**
per post. The tree is persisted in a single DynamoDB table using a
**materialized-path** design so that an arbitrary subtree can be read in one
query. Comments support **Reddit-style upvoting/downvoting** with a denormalized
score (see [Voting](#voting-upvotes--downvotes)).

**Architecture:** API Gateway (HTTP API) → Lambda (Python, AWS Lambda Powertools)
→ DynamoDB. The Lambda ships as a **container image** (not a zip), built from the
repo `Dockerfile` on the AWS-provided Python base image. All infrastructure is
defined with **AWS SAM**.

```
Client ──HTTP──▶ API Gateway ──▶ Lambda (Powertools REST resolver) ──▶ DynamoDB
```

## Tech stack

| Concern            | Choice                                   |
| ------------------ | ---------------------------------------- |
| Language           | Python 3.13                              |
| IaC                | AWS SAM (`template.yaml`)                 |
| Compute            | AWS Lambda (**container image**)         |
| Lambda packaging   | Docker image (`Dockerfile`) on `public.ecr.aws/lambda/python:3.13` |
| API                | API Gateway HTTP API                      |
| Handler framework  | AWS Lambda Powertools for Python         |
| Data store         | DynamoDB (single-table design)           |
| Configuration      | **pydantic-settings** (`settings.py`)    |
| Package management  | **uv** (never pip/poetry directly)       |
| Formatting/linting  | **ruff**                                 |
| Type checking       | **ty**                                   |
| Testing            | pytest + moto (mocked DynamoDB)          |
| Coverage gate      | **> 90%** line coverage, enforced in CI   |

## Tooling contract — non-negotiable

- **uv** manages the project. Add deps with `uv add <pkg>` / `uv add --dev <pkg>`,
  run tools with `uv run <cmd>`. Do not hand-edit the lockfile; do not invoke
  `pip` inside the venv.
- **ruff** owns formatting and linting. Do not add black/isort/flake8.
- **ty** is the type checker. Do not add mypy/pyright.
- All code is fully type-annotated. New public functions require type hints.
- **Coverage must stay above 90%.** A PR that drops coverage below the gate is
  not done. Prefer meaningful behavioural tests over tests that only chase the
  number.

### Common commands

```bash
uv sync                       # install deps from lockfile
uv run pre-commit install     # enable format + type-check git hook (one-time, per clone)
uv add aws-lambda-powertools  # add a runtime dependency
uv add --dev pytest moto      # add a dev dependency

uv run ruff format .          # format
uv run ruff check . --fix     # lint (autofix)
uv run ty check               # type check

uv run pytest                 # run tests
uv run pytest --cov=src --cov-report=term-missing --cov-fail-under=90

sam build                     # build the container image (needs Docker running)
sam local start-api           # run the API locally (invokes the image)
sam local invoke <Function>   # invoke a single function
sam deploy --guided           # first deploy (pushes the image to ECR)
```

The Lambda is packaged as a **container image**, so SAM builds and runs it with
Docker: a local Docker daemon must be running for `sam build`, `sam local ...`,
and `sam deploy`. On first deploy SAM provisions an ECR repository (via
`--resolve-image-repos` / the guided prompts) and pushes the image there.
Dependencies are installed inside the image from `uv.lock` (see the
`Dockerfile`), so there is no `src/requirements.txt` step for the zip path.

Run `ruff format`, `ruff check`, `ty check`, and the coverage gate before
considering any change complete.

## Repository layout (target)

```
.
├── template.yaml            # AWS SAM template (API GW, image Lambda, DynamoDB table + GSIs)
├── Dockerfile               # Lambda container image (uv-installed deps + src/comments)
├── .dockerignore            # keeps the Docker build context small
├── samconfig.toml           # SAM deploy config
├── pyproject.toml           # uv project + ruff/ty/pytest config
├── src/
│   └── comments/
│       ├── app.py           # Lambda entrypoint; Powertools APIGatewayRestResolver
│       ├── handlers/        # route handlers (thin)
│       ├── repository.py    # DynamoDB access — the ONLY module that talks to Dynamo
│       ├── settings.py      # pydantic-settings classes — the ONLY module that reads env vars
│       ├── models.py        # pydantic models (Comment, Post) + validation
│       ├── keys.py          # key/path construction helpers (PK/SK/GSI builders)
│       └── errors.py        # domain errors mapped to HTTP responses
└── tests/
    ├── unit/                # repository + key logic against moto
    └── integration/         # handler-level tests through the resolver
```

Keep the handler layer thin: parse/validate → call repository → serialize. All
DynamoDB key construction lives in `keys.py`; all reads/writes live in
`repository.py`. Nothing else should import `boto3`.

## Configuration

All environment configuration is declared in `settings.py` using
**pydantic-settings** — the single place the code reads environment variables.
Application code must never touch `os.environ` directly; it goes through a
cached getter (`get_database_settings()`, `get_observability_settings()`).

- One settings class per **bounded concern**, not one monolithic class:
  `DatabaseSettings` (env: `TABLE_NAME`), `ObservabilitySettings`
  (env: `POWERTOOLS_*`). A new concern (e.g. auth, feature flags) gets its own
  class — do not grow an existing one past its concern.
- Settings classes are `frozen=True`; instances are cached via `lru_cache`
  getters. Tests that mutate the environment call `reset_settings()` (an
  autouse fixture in `tests/unit/test_settings.py` shows the pattern).
- A new env var is added in three places together: `template.yaml`
  (`Environment.Variables`), the matching settings class, and
  `tests/conftest.py`.

## Data model — DynamoDB single table

One table, `Comments`. Comment position in the tree is encoded as a
**materialized path** in the sort key, which makes "read a whole subtree"
a single `begins_with` query.

- Sibling ordering uses **ULIDs** as path segments so the SK sorts
  chronologically within each level.
- Each comment stores its full path, `parent_id`, and `depth`.
- Deletes are **soft** (tombstone) so replies under a deleted comment survive;
  the item stays but `content` is cleared and `deleted = true`.

### Key schema

| Entity  | PK              | SK                                  |
| ------- | --------------- | ----------------------------------- |
| Post    | `POST#<postId>` | `META`                              |
| Comment | `POST#<postId>` | `COMMENT#<seg1>#<seg2>#…#<segN>`     |
| Vote    | `POST#<postId>` | `VOTE#<userId>#<commentId>`          |

Where `seg1..segN` is the ULID path from the root comment down to this node.
A root (top-level) comment has a single-segment path (`depth = 0`).

Vote items live in the **same partition** as the comment they target, so a
comment's score and a user's vote can be updated together in one
`TransactWriteItems`. Putting `userId` before `commentId` in the SK means all of
one user's votes on a post are a single `begins_with(SK, "VOTE#<userId>#")`
query — exactly what you need to render highlighted arrows for a whole page.
See [Voting](#voting-upvotes--downvotes).

### GSI1 — comments by user

| Key       | Value                                  |
| --------- | -------------------------------------- |
| `GSI1PK`  | `USER#<userId>`                        |
| `GSI1SK`  | `TS#<createdAt-ISO>#<commentId>`       |

Lets us list everything a user wrote across all posts, newest first, without
scanning. GSI1 is **overloaded** for vote items too (see Voting) so a user's
votes across all posts are queryable from the same index.

### GSI2 — comments by depth

| Key      | Value                                        |
| -------- | -------------------------------------------- |
| `GSI2PK` | `POST#<postId>`                              |
| `GSI2SK` | `DEPTH#<zero-padded depth>#<path>`           |

Makes `depth` a real **key condition** for depth-bounded reads (#3, #5, #6, #7)
instead of a post-read `FilterExpression` — see
[Depth reads](#depth-reads--implementation) for why and for the query shapes.
GSI2 is **sparse**: only comment items set `GSI2PK`/`GSI2SK` (posts and votes
don't), so depth queries never touch non-comment items. `depth` is zero-padded
to 4 digits in the key so lexical sort matches numeric order.

### Item attributes

**Comment:** `comment_id` (ULID), `post_id`, `user_id`, `parent_id` (nullable),
`path`, `depth`, `content`, `created_at`, `updated_at`, `deleted` (bool),
plus denormalized vote counters `upvotes`, `downvotes`, `score` (all `Number`,
default `0`), plus `PK`/`SK`/`GSI1PK`/`GSI1SK`/`GSI2PK`/`GSI2SK`.

**Vote:** `post_id`, `comment_id`, `user_id`, `value` (`+1` or `-1`),
`created_at`, `updated_at`, plus `PK`/`SK`/`GSI1PK`/`GSI1SK`. A vote's existence
*is* the record that a user voted; removing a vote **deletes** the item.

`depth` is a **0-based integer** (root comment = `0`). It is stored twice: as a
plain `Number` attribute (so comparison operators behave numerically) and
**zero-padded** inside `GSI2SK` (`DEPTH#0003#<path>`, so lexical key sort
matches numeric order).

## Access patterns (enumerated)

The schema above is derived from these. Any new access pattern must be added
here first, then to the schema/GSIs — never bolt on a `Scan`.

| # | Access pattern                                             | Operation | Keys / condition                                                                 |
| - | ---------------------------------------------------------- | --------- | -------------------------------------------------------------------------------- |
| 1 | Get post metadata                                          | GetItem   | `PK = POST#<postId>`, `SK = META`                                                |
| 2 | Get the **entire comment tree** for a post                 | Query     | `PK = POST#<postId>` AND `begins_with(SK, "COMMENT#")`                            |
| 3 | Get **root / top-level** comments for a post               | Query (GSI2) | `GSI2PK = POST#<postId>` AND `begins_with(GSI2SK, "DEPTH#0000#")`              |
| 4 | Get a **subtree** rooted at a comment (node + descendants) | Query     | `PK = POST#<postId>` AND `begins_with(SK, "COMMENT#<path>")`                      |
| 5 | Get **direct replies** (children) of a comment             | Query (GSI2) | `begins_with(GSI2SK, "DEPTH#<parentDepth+1>#<parentPath>#")`                   |
| 6 | Read a tree/subtree **up to a max depth** (threaded view)  | Query (GSI2) | whole tree: `GSI2SK <= "DEPTH#<maxD>#￿"`; subtree: one #5-style query per level |
| 7 | Get all comments **at exactly depth N** in a post          | Query (GSI2) | `begins_with(GSI2SK, "DEPTH#<000N>#")`                                          |
| 8 | Get a single comment by id                                 | GetItem   | `PK = POST#<postId>`, `SK = COMMENT#<path>`                                       |
| 9 | List all comments by a **user across all trees**, newest first | Query (GSI1) | `GSI1PK = USER#<userId>`, `ScanIndexForward = false`                          |
|10 | List a user's comments **since a timestamp**               | Query (GSI1) | `GSI1PK = USER#<userId>` AND `GSI1SK > TS#<iso>`                              |
|11 | List a user's comments **within one post**                 | Query (GSI1) | pattern #9, `FilterExpression: post_id = <postId>` (or add GSI3 if hot)       |
|12 | Add a comment (root or reply)                              | PutItem   | build path from parent's path + new ULID; set `depth = parentDepth + 1`; `ConditionExpression` parent exists |
|13 | Soft-delete a comment (preserve replies)                   | UpdateItem| set `deleted = true`, clear `content`; keep item so child paths stay valid        |
|14 | Edit a comment                                             | UpdateItem| `PK`+`SK`, set `content`, `updated_at`; `ConditionExpression` not `deleted`       |
|15 | Paginate any list                                          | Query     | pass `ExclusiveStartKey` through to the API as an opaque cursor                   |

### Notes / trade-offs

- **Materialized path vs adjacency list.** We use materialized path because the
  primary read is "give me a whole tree/subtree in one query" (patterns #2, #4).
  The cost is that a node's path is fixed at creation — we do **not** support
  re-parenting a comment. If re-parenting is ever required, revisit this.
- **Pattern #11** is served today by filtering GSI1; promote it to its own GSI
  (`GSI3PK = USER#<u>#POST#<p>`) only if it becomes a hot path.
- Path segments are ULIDs, so siblings are naturally time-ordered and writes
  don't need a read-modify-write to compute an index.

### Depth reads — implementation

Depth-based reads (#3, #5, #6, #7) are **first-class** and are served by
**GSI2**, where depth is part of the sort key and therefore a real **key
condition**:

- Root only: `GSI2PK = POST#<id>` AND `begins_with(GSI2SK, "DEPTH#0000#")`
- Exactly depth N: `begins_with(GSI2SK, "DEPTH#000N#")`
- Direct children of a parent: `begins_with(GSI2SK, "DEPTH#<parentDepth+1>#<parentPath>#")`
  — fixed-length ULID segments guarantee the path prefix can't match a sibling.
- Whole tree up to max depth D: `GSI2SK <= "DEPTH#000D#￿"` (range read, no filter)
- Subtree up to max depth D: one direct-children-style query **per level**
  from the root's depth down to D, stopping at the first empty level (an empty
  tree level can have nothing below it). Level count is small in practice, and
  each query reads exactly the comments it returns.

Why a GSI rather than `FilterExpression: depth <= D` on the partition query:
DynamoDB applies filters **after** the read, so a filtered query bills RCUs for
the **whole** matched tree/subtree even when the client only sees one level —
"read the direct children of a hot parent" would cost the parent's entire
subtree. GSI2 was promoted from an escalation option to the default because of
exactly that amplification. The cost is a second GSI (extra write + storage)
on every comment write.

Two behavioral notes:
- GSI2 returns items in **depth-major** order (all of depth 0, then depth 1, …),
  not path order. Complete reads are re-sorted into path order in the
  repository; *paginated* depth-bounded reads keep depth-major page order.
- `depth` in `GSI2SK` is zero-padded to 4 digits, so keyed depth maxes out at
  9999 (`keys.MAX_KEYED_DEPTH`); validate user-supplied `max_depth` against it.

**Bounded reads (#6)** are the main reason depth is stored: rendering a threaded
UI that shows the first N levels and lazy-loads deeper subtrees on demand
(via #4 rooted at the "load more" node). Prefer a bounded read over pulling an
entire deep tree in one query.

## Voting (upvotes / downvotes)

Reddit-style voting: each user may cast **one** vote per comment (`+1` or `-1`),
change it, or remove it. Each comment keeps **denormalized** `upvotes`,
`downvotes`, and `score` (= upvotes − downvotes) so reads never aggregate votes.

### Invariants

- **One vote per (user, comment)** — enforced by the vote item's key
  (`SK = VOTE#<userId>#<commentId>`); a second vote overwrites the first.
- Comment counters and the vote item are **always mutated together** in a single
  `TransactWriteItems` — they must never drift.
- You cannot vote on a `deleted` comment.
- A vote's `value` is only ever `+1` or `-1`; `0` means *no vote*, represented by
  the **absence** of the item.

### Casting a vote (the delta transaction)

Voting is read-then-transact with optimistic concurrency, because changing a
vote needs the previous value to compute the counter delta:

1. Read the caller's existing vote item (if any) → `prev ∈ {none, +1, −1}`.
2. Compute deltas for `upvotes` / `downvotes` / `score` from `(prev → new)`
   (e.g. `+1 → −1` ⇒ `upvotes −1`, `downvotes +1`, `score −2`).
3. `TransactWriteItems`:
   - **Put** the vote item, `ConditionExpression` that its current `value`
     equals `prev` (or that it doesn't exist) — guards against a concurrent vote.
   - **Update** the comment with `ADD upvotes/downvotes/score <deltas>` and a
     `ConditionExpression attribute_not_exists(deleted) OR deleted = false`.

**Removing a vote** is the same shape: `Delete` the vote item + `ADD` the inverse
delta to the counters, both conditional.

### Access patterns

| #  | Access pattern                                              | Operation | Keys / condition                                                                 |
| -- | ---------------------------------------------------------- | --------- | -------------------------------------------------------------------------------- |
| V1 | Cast / change a vote                                        | TransactWriteItems | Put `VOTE#<userId>#<commentId>` + `ADD` comment counters (deltas), both conditional |
| V2 | Remove a vote                                               | TransactWriteItems | Delete vote item + `ADD` inverse delta, both conditional                          |
| V3 | Get a comment's score                                       | —         | Free — read `score`/`upvotes`/`downvotes` off the comment item (patterns #2/#4/#8) |
| V4 | Get **how one user voted** on a comment                     | GetItem   | `PK = POST#<postId>`, `SK = VOTE#<userId>#<commentId>`                            |
| V5 | Get **a user's votes across a whole post** (render arrows)  | Query     | `PK = POST#<postId>` AND `begins_with(SK, "VOTE#<userId>#")`                      |
| V6 | List a user's votes **across all posts**                    | Query (GSI1) | `GSI1PK = USER#<userId>` AND `begins_with(GSI1SK, "VOTE#")` (filter `value = 1` for upvoted only) |
| V7 | Sort a tree/subtree **by score** ("top")                    | Query + sort | read via #2/#4, sort by `score` in the handler (see below)                    |

For V6, vote items set `GSI1PK = USER#<userId>`, `GSI1SK = VOTE#<createdAt>#<postId>#<commentId>`.

### Sorting by score — trade-off

Comment queries (#2/#4) return items in **path order** (chronological), not score
order. Default to sorting by `score` **in the handler** after reading the
tree/subtree — correct and cheap for normal-sized threads. Do **not** add a
score-keyed GSI: `score` changes on every vote, so it would create a hot,
churning index. If "top" sort over very large trees ever becomes a bottleneck,
precompute a periodic `rank` snapshot rather than indexing live `score`.
Reddit's "best" ordering is a **Wilson score** on `(upvotes, downvotes)` computed
in the handler — same read path, different comparator.

## Powertools & handler conventions

- Use `APIGatewayRestResolver` (or `APIGatewayHttpResolver` to match the SAM API
  type) for routing; one resolver per Lambda.
- Enable the Powertools **Logger**, **Tracer**, and **Metrics**; decorate the
  handler with `@logger.inject_lambda_context` and `@tracer.capture_lambda_handler`.
- Validate request bodies with pydantic models from `models.py`; never trust raw
  event input.
- Map domain errors (`errors.py`) to HTTP status codes centrally via
  `app.exception_handler(...)`. Return structured JSON error bodies.
- Never `print`; log through the Powertools logger.

## Testing conventions

- Mock DynamoDB with **moto**; create the table (with GSI1 and GSI2) in a fixture that
  mirrors `template.yaml`.
- Test the repository against the real key/path logic — assert on PK/SK/GSI
  values, not just return objects.
- Cover each access pattern above with at least one test, including tree/subtree
  reads and the soft-delete-preserves-children case.
- **Voting** needs dedicated tests: the full `(prev → new)` delta matrix
  (none→up, up→down, down→remove, etc.) with counter assertions; the
  one-vote-per-user invariant; rejecting votes on deleted comments; and the
  optimistic-concurrency `ConditionExpression` failure path. moto supports
  `TransactWriteItems`, so exercise the real transaction.
- Keep coverage **> 90%**; wire `--cov-fail-under=90` into the pytest config and
  CI so the gate can't be bypassed.
