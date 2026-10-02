from pydantic import BaseModel

class ProjectCreate(BaseModel):
    project_name: str
    project_client: str
    project_type: str
    assigned_persons: list[str]
    project_status: str
    project_note: str