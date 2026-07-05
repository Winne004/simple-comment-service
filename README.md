# simple-comment-service

Serverless comment API: API Gateway (HTTP API) → Lambda (Python, AWS Lambda
Powertools) → DynamoDB. Comments form a tree per post, stored with a
materialized-path single-table design, with Reddit-style up/down voting and
denormalized scores. See [CLAUDE.md](CLAUDE.md) for the full data model and
access patterns.

## API

All mutating endpoints identify the caller via the `x-user-id` header.

| Method | Path | Description |
| ------ | ---- | ----------- |
| POST   | `/posts` | Create a post |
| GET    | `/posts/{post_id}` | Post metadata |
| GET    | `/posts/{post_id}/comments` | Comment tree (`max_depth`, `sort=new\|top`, `limit`, `cursor`) |
| POST   | `/posts/{post_id}/comments` | Add a comment (`parent_id` for replies) |
| GET    | `/posts/{post_id}/comments/{id}` | Single comment |
| GET    | `/posts/{post_id}/comments/{id}/replies` | Descendants (`direct=true` for children only) |
| PATCH  | `/posts/{post_id}/comments/{id}` | Edit own comment |
| DELETE | `/posts/{post_id}/comments/{id}` | Soft-delete own comment (replies survive) |
| PUT    | `/posts/{post_id}/comments/{id}/vote` | Cast/change vote (`{"value": 1\|-1}`) |
| DELETE | `/posts/{post_id}/comments/{id}/vote` | Remove vote |
| GET    | `/posts/{post_id}/comments/{id}/vote` | Caller's vote on a comment |
| GET    | `/posts/{post_id}/votes` | Caller's votes across a post |
| GET    | `/users/{user_id}/comments` | User's comments (`since`, `post_id`, `limit`, `cursor`) |
| GET    | `/users/{user_id}/votes` | User's votes across posts (`value=1\|-1`) |

## Development

```bash
uv sync                       # install deps
uv run ruff format .          # format
uv run ruff check .           # lint
uv run ty check               # type check
uv run pytest                 # tests + coverage gate (>90%)
```

## Deployment (AWS SAM)

SAM builds the Lambda from `src/requirements.txt`, exported from the lockfile:

```bash
uv export --no-dev --no-emit-project --format requirements-txt -o src/requirements.txt
sam build
sam deploy --guided           # first deploy
sam local start-api           # run locally
```

## Test frontend

A minimal React UI for exercising the API lives in [`frontend/`](frontend/README.md):

```bash
cd frontend
npm install
VITE_API_BASE_URL=http://127.0.0.1:3000 npm run dev
```

The base URL can also be set via `frontend/.env` or edited live in the UI.
