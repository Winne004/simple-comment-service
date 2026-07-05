# Comment Service Tester

A minimal React (Vite) UI for exercising the comment API: create/load posts,
threaded comments (reply/edit/soft-delete), and Reddit-style voting.

## Setup

```bash
cd frontend
npm install
cp .env.example .env   # then edit VITE_API_BASE_URL
npm run dev            # http://localhost:5173
```

## Configuring the API base URL

- **Env var (build/dev time):** set `VITE_API_BASE_URL` in `.env` /
  `.env.local`, or inline: `VITE_API_BASE_URL=https://... npm run dev`.
- **Runtime override:** the "API base URL" field in the UI wins over the env
  var and persists in localStorage. Clear the field's stored value by editing
  it back, or wipe localStorage.

Point it at either a deployed stack (the `ApiUrl` output of `sam deploy`) or
`sam local start-api` (`http://127.0.0.1:3000`).

The API identifies callers by an `x-user-id` header — set any string in the
"User ID" field to act as that user (votes/edits/deletes are per-user).
