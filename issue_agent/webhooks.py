"""GitHub signed event ingress. Payloads are data, never instructions."""
import hashlib
import hmac
import json
import re

from fastapi import Request
from fastapi.responses import JSONResponse

from .domain import TaskRequest
from .policy import load_policy


async def receive_webhook(request: Request, settings, store):
    secret = settings.webhook_secret.get_secret_value()
    if not secret:
        return JSONResponse({"error": "webhook_disabled"}, status_code=503)
    if settings.tool_mode != "github":
        return JSONResponse({"error": "github_mode_required"}, status_code=409)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 1_048_576:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        chunks.append(chunk)
    body = b"".join(chunks)
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, request.headers.get("x-hub-signature-256", "")):
        return JSONResponse({"error": "invalid_signature"}, status_code=401)
    delivery = request.headers.get("x-github-delivery", "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", delivery):
        return JSONResponse({"error": "invalid_delivery"}, status_code=422)
    try:
        payload = json.loads(body)
        repository = payload["repository"]["full_name"]
        if repository.lower() != settings.repository.lower():
            return JSONResponse({"error": "repository_not_allowed"}, status_code=403)
        event, action = request.headers.get("x-github-event"), payload.get("action")
        accepted = (event == "issues" and action in {"opened", "edited", "reopened"}) or (
            event == "issue_comment" and action in {"created", "edited", "deleted"})
        issue = payload.get("issue", {})
        if not accepted or "pull_request" in issue or payload.get("sender", {}).get("type") == "Bot":
            return JSONResponse({"status": "ignored"}, status_code=202)
        number = issue["number"]
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError("invalid issue number")
        if event == "issue_comment" and store.own_comment(
                number, settings.repository, payload.get("comment", {}).get("body", "")):
            return JSONResponse({"status": "ignored_own_output"}, status_code=202)
        policy = load_policy(settings.policy_path)
        task = TaskRequest(issue_number=number, propose_actions=policy.propose_on_webhook)
        data = {**task.model_dump(), "repository": settings.repository,
                "tool_mode": settings.tool_mode, "policy": policy.model_dump()}
        # Issue bodies from the event are not trusted as the current snapshot; worker fetches it.
        task_id = store.submit(data, limit=settings.queue_limit, delivery=delivery,
                               payload_hash=hashlib.sha256(body).hexdigest())
        return JSONResponse({"id": task_id, "status": "accepted"}, status_code=202)
    except (ValueError, KeyError, TypeError, AttributeError):
        return JSONResponse({"error": "invalid_payload"}, status_code=422)
