from pydantic import BaseModel, Field


class ProjectFieldCreate(BaseModel):
    key: str | None = None
    label: str
    data_type: str = "text"
    source: str = "import"
    capture_method: str = "manual"
    required: bool = False
    parent_key: str | None = None
    kpi_enabled: bool = False
    options: list[str] = Field(default_factory=list)


class ProjectWorkItemSchemaCreate(BaseModel):
    primary_field: ProjectFieldCreate | None = None
    aggregate_field: ProjectFieldCreate | None = None
    custom_fields: list[ProjectFieldCreate] = Field(default_factory=list)


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    module_ids: list[str] = Field(default_factory=list)
    work_item_schema: ProjectWorkItemSchemaCreate | None = None
