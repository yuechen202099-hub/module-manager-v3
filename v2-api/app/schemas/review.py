from pydantic import BaseModel


class GroupReviewUpdate(BaseModel):
    status: str
    comment: str | None = None


class ExceptionCreate(BaseModel):
    kind: str
    description: str

