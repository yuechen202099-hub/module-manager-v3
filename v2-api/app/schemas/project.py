from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    module_ids: list[str] = Field(default_factory=list)
