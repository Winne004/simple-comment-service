"""Domain errors, mapped centrally to HTTP responses in app.py."""


class DomainError(Exception):
    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class PostNotFoundError(DomainError):
    status_code = 404
    error_code = "post_not_found"

    def __init__(self, post_id: str) -> None:
        super().__init__(f"Post {post_id} not found")


class CommentNotFoundError(DomainError):
    status_code = 404
    error_code = "comment_not_found"

    def __init__(self, comment_id: str) -> None:
        super().__init__(f"Comment {comment_id} not found")


class VoteNotFoundError(DomainError):
    status_code = 404
    error_code = "vote_not_found"

    def __init__(self, comment_id: str) -> None:
        super().__init__(f"No vote on comment {comment_id}")


class CommentDeletedError(DomainError):
    status_code = 409
    error_code = "comment_deleted"

    def __init__(self, comment_id: str) -> None:
        super().__init__(f"Comment {comment_id} is deleted")


class ForbiddenError(DomainError):
    status_code = 403
    error_code = "forbidden"


class VoteConflictError(DomainError):
    status_code = 409
    error_code = "vote_conflict"

    def __init__(self, comment_id: str) -> None:
        super().__init__(f"Concurrent vote on comment {comment_id}; retry")


class InvalidCursorError(DomainError):
    status_code = 400
    error_code = "invalid_cursor"

    def __init__(self) -> None:
        super().__init__("Invalid pagination cursor")
