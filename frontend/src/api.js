// Thin fetch client for the comment service. Base URL priority:
// runtime override (localStorage) > VITE_API_BASE_URL > sam local default.
export const DEFAULT_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:3000";

export class ApiError extends Error {
  constructor(status, body) {
    super(`HTTP ${status}: ${typeof body === "string" ? body : JSON.stringify(body)}`);
    this.status = status;
    this.body = body;
  }
}

async function request(baseUrl, userId, method, path, body) {
  const headers = { "content-type": "application/json" };
  if (userId) headers["x-user-id"] = userId;
  const res = await fetch(`${baseUrl.replace(/\/+$/, "")}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = text;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* leave as text */
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export function makeClient(baseUrl, userId) {
  const call = (method, path, body) => request(baseUrl, userId, method, path, body);
  const q = (params) => {
    const filtered = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
    return filtered.length ? `?${new URLSearchParams(Object.fromEntries(filtered))}` : "";
  };
  return {
    createPost: (title) => call("POST", "/posts", { title }),
    getPost: (postId) => call("GET", `/posts/${postId}`),
    getTree: (postId, { sort, maxDepth, limit, cursor } = {}) =>
      call(
        "GET",
        `/posts/${postId}/comments${q({ sort, max_depth: maxDepth, limit, cursor })}`
      ),
    createComment: (postId, content, parentId) =>
      call("POST", `/posts/${postId}/comments`, {
        content,
        parent_id: parentId ?? null,
      }),
    editComment: (postId, commentId, content) =>
      call("PATCH", `/posts/${postId}/comments/${commentId}`, { content }),
    deleteComment: (postId, commentId) =>
      call("DELETE", `/posts/${postId}/comments/${commentId}`),
    castVote: (postId, commentId, value) =>
      call("PUT", `/posts/${postId}/comments/${commentId}/vote`, { value }),
    removeVote: (postId, commentId) =>
      call("DELETE", `/posts/${postId}/comments/${commentId}/vote`),
    listMyVotesOnPost: (postId) => call("GET", `/posts/${postId}/votes`),
    listUserComments: (userId2, params = {}) =>
      call("GET", `/users/${userId2}/comments${q(params)}`),
  };
}
