"""Pydantic domain models and request bodies."""

from typing import Literal

from pydantic import BaseModel, Field


class Post(BaseModel):
    post_id: str
    title: str
    created_at: str


class Comment(BaseModel):
    comment_id: str
    post_id: str
    user_id: str
    parent_id: str | None = None
    path: str
    depth: int
    content: str
    created_at: str
    updated_at: str
    deleted: bool = False
    upvotes: int = 0
    downvotes: int = 0
    score: int = 0


class Vote(BaseModel):
    post_id: str
    comment_id: str
    user_id: str
    value: int
    created_at: str
    updated_at: str


class CreatePostBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class CreateCommentBody(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    parent_id: str | None = None


class EditCommentBody(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class VoteBody(BaseModel):
    value: Literal[1, -1]
