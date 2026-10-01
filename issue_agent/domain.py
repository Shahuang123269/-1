import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_number: int = Field(gt=0)
    goal: str = Field(default="检查信息完整性并提出处理建议", min_length=1, max_length=2000)
    propose_actions: bool = False


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["comment", "add_labels"]
    body: str = Field(default="", max_length=4000)
    labels: list[Literal["bug", "enhancement", "needs-info", "triage"]] = Field(
        default_factory=list, max_length=4
    )


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    quote: str = Field(min_length=1, max_length=500)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=4000)
    missing_fields: list[Literal["reproduction", "environment", "actual", "expected"]] = Field(
        description="Bug report fields absent from issue body and comments. Brief but present fields are not missing; discuss quality in summary. Enhancement reports use an empty array. Title is used for intent classification, not form completeness."
    )
    category: Literal["bug", "enhancement", "uncertain"]
    priority: Literal["high", "normal", "unknown"]
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    actions: list[Action] = Field(default_factory=list, max_length=2)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "reject"]


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def action_digest(repository: str, issue_number: int, actions: list[dict]) -> str:
    payload = {"repository": repository, "issue_number": issue_number, "actions": actions}
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


class DomainError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)
