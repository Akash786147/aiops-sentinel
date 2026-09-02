from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    use_rag: bool = True


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=2, max_length=80)
    action: Literal["create_fix_branch", "scale_out", "restart_service"] = "create_fix_branch"


class MetricSnapshot(BaseModel):
    request_count: int
    error_count: int
    error_rate: float
    p95_ms: float
    cpu_percent: float
    memory_mb: float
