import { useCallback, useMemo, useState } from "react";
import { DEFAULT_BASE_URL, makeClient } from "./api.js";

function useLocalStorage(key, initial) {
  const [value, setValue] = useState(() => localStorage.getItem(key) ?? initial);
  const set = useCallback(
    (v) => {
      setValue(v);
      localStorage.setItem(key, v);
    },
    [key]
  );
  return [value, set];
}

function buildTree(items) {
  const byId = new Map(items.map((c) => [c.comment_id, { ...c, children: [] }]));
  const roots = [];
  for (const node of byId.values()) {
    const parent = node.parent_id ? byId.get(node.parent_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  }
  return roots;
}

function CommentNode({ comment, myVotes, onReply, onEdit, onDelete, onVote }) {
  const [replyText, setReplyText] = useState("");
  const [editText, setEditText] = useState(null); // null = not editing
  const myVote = myVotes[comment.comment_id];

  return (
    <div className="comment">
      <div className="comment-header">
        <span className="votes">
          <button
            className={myVote === 1 ? "vote active-up" : "vote"}
            title="Upvote"
            onClick={() => onVote(comment, myVote === 1 ? null : 1)}
          >
            ▲
          </button>
          <span className="score">{comment.score}</span>
          <button
            className={myVote === -1 ? "vote active-down" : "vote"}
            title="Downvote"
            onClick={() => onVote(comment, myVote === -1 ? null : -1)}
          >
            ▼
          </button>
        </span>
        <strong>{comment.user_id}</strong>
        <span className="meta">
          depth {comment.depth} · id {comment.comment_id} · ▲{comment.upvotes} ▼
          {comment.downvotes}
          {comment.updated_at !== comment.created_at && " · edited"}
        </span>
      </div>

      {editText === null ? (
        <div className={comment.deleted ? "content deleted" : "content"}>
          {comment.deleted ? "[deleted]" : comment.content}
        </div>
      ) : (
        <div className="inline-form">
          <input value={editText} onChange={(e) => setEditText(e.target.value)} />
          <button
            onClick={() => onEdit(comment, editText).then(() => setEditText(null))}
          >
            Save
          </button>
          <button onClick={() => setEditText(null)}>Cancel</button>
        </div>
      )}

      {!comment.deleted && (
        <div className="actions">
          <button onClick={() => setEditText(comment.content)}>Edit</button>
          <button onClick={() => onDelete(comment)}>Delete</button>
        </div>
      )}

      <div className="inline-form">
        <input
          placeholder="Reply…"
          value={replyText}
          onChange={(e) => setReplyText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && replyText.trim())
              onReply(comment, replyText).then(() => setReplyText(""));
          }}
        />
        <button
          disabled={!replyText.trim()}
          onClick={() => onReply(comment, replyText).then(() => setReplyText(""))}
        >
          Reply
        </button>
      </div>

      {comment.children.length > 0 && (
        <div className="children">
          {comment.children.map((child) => (
            <CommentNode
              key={child.comment_id}
              comment={child}
              myVotes={myVotes}
              onReply={onReply}
              onEdit={onEdit}
              onDelete={onDelete}
              onVote={onVote}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [baseUrl, setBaseUrl] = useLocalStorage("baseUrl", DEFAULT_BASE_URL);
  const [userId, setUserId] = useLocalStorage("userId", "test-user");
  const api = useMemo(() => makeClient(baseUrl, userId), [baseUrl, userId]);

  const [post, setPost] = useState(null);
  const [postIdInput, setPostIdInput] = useState("");
  const [newPostTitle, setNewPostTitle] = useState("");

  const [comments, setComments] = useState([]);
  const [myVotes, setMyVotes] = useState({}); // comment_id -> 1 | -1
  const [sort, setSort] = useState("new");
  const [maxDepth, setMaxDepth] = useState("");
  const [newComment, setNewComment] = useState("");

  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (fn) => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
      throw e;
    } finally {
      setBusy(false);
    }
  }, []);

  const refreshTree = useCallback(
    (postId) =>
      run(async () => {
        const [tree, votes] = await Promise.all([
          api.getTree(postId, { sort, maxDepth: maxDepth || undefined }),
          api.listMyVotesOnPost(postId),
        ]);
        setComments(tree.items);
        setMyVotes(
          Object.fromEntries(votes.items.map((v) => [v.comment_id, v.value]))
        );
      }),
    [api, run, sort, maxDepth]
  );

  const loadPost = (postId) =>
    run(async () => {
      const p = await api.getPost(postId);
      setPost(p);
      await refreshTree(p.post_id);
    });

  const createPost = () =>
    run(async () => {
      const p = await api.createPost(newPostTitle);
      setNewPostTitle("");
      setPost(p);
      setComments([]);
      setMyVotes({});
    });

  const addComment = (parent, content) =>
    run(async () => {
      await api.createComment(post.post_id, content, parent?.comment_id);
      await refreshTree(post.post_id);
    });

  const editComment = (comment, content) =>
    run(async () => {
      await api.editComment(post.post_id, comment.comment_id, content);
      await refreshTree(post.post_id);
    });

  const deleteComment = (comment) =>
    run(async () => {
      await api.deleteComment(post.post_id, comment.comment_id);
      await refreshTree(post.post_id);
    });

  const vote = (comment, value) =>
    run(async () => {
      if (value === null) await api.removeVote(post.post_id, comment.comment_id);
      else await api.castVote(post.post_id, comment.comment_id, value);
      await refreshTree(post.post_id);
    });

  const tree = useMemo(() => buildTree(comments), [comments]);

  return (
    <div className="app">
      <h1>Comment Service Tester</h1>

      <section className="config">
        <label>
          API base URL
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://xxx.execute-api.eu-west-1.amazonaws.com"
          />
        </label>
        <label>
          User ID (x-user-id header)
          <input value={userId} onChange={(e) => setUserId(e.target.value)} />
        </label>
        <div className="hint">
          Default comes from <code>VITE_API_BASE_URL</code>; edits here are saved in
          localStorage.
        </div>
      </section>

      {error && <div className="error">{error}</div>}
      {busy && <div className="busy">Loading…</div>}

      <section className="row">
        <div className="panel">
          <h2>Create post</h2>
          <div className="inline-form">
            <input
              placeholder="Post title"
              value={newPostTitle}
              onChange={(e) => setNewPostTitle(e.target.value)}
            />
            <button disabled={!newPostTitle.trim()} onClick={createPost}>
              Create
            </button>
          </div>
        </div>
        <div className="panel">
          <h2>Load post</h2>
          <div className="inline-form">
            <input
              placeholder="Post ID"
              value={postIdInput}
              onChange={(e) => setPostIdInput(e.target.value)}
            />
            <button disabled={!postIdInput.trim()} onClick={() => loadPost(postIdInput.trim())}>
              Load
            </button>
          </div>
        </div>
      </section>

      {post && (
        <section className="panel">
          <h2>
            {post.title} <span className="meta">({post.post_id})</span>
          </h2>

          <div className="inline-form">
            <label>
              Sort
              <select value={sort} onChange={(e) => setSort(e.target.value)}>
                <option value="new">new</option>
                <option value="top">top</option>
              </select>
            </label>
            <label>
              Max depth
              <input
                type="number"
                min="0"
                placeholder="∞"
                value={maxDepth}
                onChange={(e) => setMaxDepth(e.target.value)}
                style={{ width: "5em" }}
              />
            </label>
            <button onClick={() => refreshTree(post.post_id)}>Refresh</button>
          </div>

          <div className="inline-form">
            <input
              placeholder="Write a top-level comment…"
              value={newComment}
              onChange={(e) => setNewComment(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newComment.trim())
                  addComment(null, newComment).then(() => setNewComment(""));
              }}
            />
            <button
              disabled={!newComment.trim()}
              onClick={() => addComment(null, newComment).then(() => setNewComment(""))}
            >
              Comment
            </button>
          </div>

          {tree.length === 0 ? (
            <p className="meta">No comments yet.</p>
          ) : (
            tree.map((c) => (
              <CommentNode
                key={c.comment_id}
                comment={c}
                myVotes={myVotes}
                onReply={addComment}
                onEdit={editComment}
                onDelete={deleteComment}
                onVote={vote}
              />
            ))
          )}
        </section>
      )}
    </div>
  );
}
