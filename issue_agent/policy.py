"""Operator-owned policy; issue content cannot change write permissions."""
import hashlib
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import Action, DomainError, canonical


class RepositoryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default-triage"
    version: str = "1"
    required_fields: list[Literal["reproduction", "environment", "actual", "expected"]] = Field(
        default_factory=lambda: ["reproduction", "environment", "actual", "expected"]
    )
    allowed_labels: list[str] = Field(
        default_factory=lambda: ["bug", "enhancement", "needs-info", "triage"], max_length=20
    )
    label_mapping: dict[str, str] = Field(default_factory=lambda: {
        "bug": "bug", "enhancement": "enhancement", "needs-info": "needs-info",
        "uncertain": "triage",
    })
    comment_prefix: str = Field(default="为进一步排查，请补充：", max_length=200)
    propose_on_webhook: bool = True

    @model_validator(mode="after")
    def valid_mapping(self):
        if set(self.label_mapping) != {"bug", "enhancement", "needs-info", "uncertain"}:
            raise ValueError("label_mapping must cover all four triage categories")
        if not set(self.label_mapping.values()).issubset(self.allowed_labels):
            raise ValueError("mapped labels must be allowed")
        if any(not label.strip() or len(label) > 50 for label in self.allowed_labels):
            raise ValueError("invalid label")
        if len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("duplicate required field")
        return self

    def validate_actions(self, actions: list[dict]):
        if len(actions) > 2 or len({a["kind"] for a in actions}) != len(actions):
            raise DomainError("invalid_action")
        for raw in actions:
            a = Action.model_validate(raw)
            if a.kind == "comment" and (not a.body.strip() or a.labels):
                raise DomainError("invalid_action")
            if a.kind == "add_labels" and (a.body or not a.labels):
                raise DomainError("invalid_action")
            if not set(a.labels).issubset(self.allowed_labels):
                raise DomainError("label_not_allowed")


def load_policy(path: Path | None) -> RepositoryPolicy:
    if path is None:
        return RepositoryPolicy()
    with path.open("rb") as stream:
        return RepositoryPolicy.model_validate(tomllib.load(stream))


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def input_snapshot(issue: dict, comments: list[dict], own_bodies=()) -> dict:
    # Labels are outputs, not evidence for form completeness. Exact known receipts only
    # are excluded; an arbitrary user-supplied marker never suppresses input changes.
    return {
        "number": issue["number"], "title": issue["title"], "body": issue["body"],
        "state": issue.get("state", "open"),
        "comments": [
            {"id": c["id"], "body": c["body"], "source": c["source"]}
            for c in comments if c["body"] not in own_bodies
        ],
    }


def plan_digest(task_id, version, request, result, context):
    return fingerprint({
        "task_id": task_id, "version": version, "repository": request["repository"],
        "issue_number": request["issue_number"], "actions": result["actions"],
        "context": context,
    })
