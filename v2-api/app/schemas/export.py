from pydantic import BaseModel


class TaskDetailExportRequest(BaseModel):
    task_id: int


class FinalDeliveryExportRequest(BaseModel):
    project_id: int

