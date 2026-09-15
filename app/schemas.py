from pydantic import BaseModel


class LoginForm(BaseModel):
    email: str
    password: str


class SearchQueryCreate(BaseModel):
    title: str
    keywords: str


class ChannelCreate(BaseModel):
    username: str


class CommentCreate(BaseModel):
    text: str


class StatusUpdate(BaseModel):
    status: str
