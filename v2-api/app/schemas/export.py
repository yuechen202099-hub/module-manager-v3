from pydantic import BaseModel


class TaskDetailExportRequest(BaseModel):
    task_id: int


class FinalDeliveryExportRequest(BaseModel):
    project_id: int | None = None
    task_id: int | None = None
    terminal: str = ""
    review_scope: str = "reviewed"


class ExceptionMetersExportRequest(BaseModel):
    reviewer: str = ""
