"""Collect explicitly selected public issues with GET only; no credentials or LLM.

Snapshots are local data, not automatically labeled evaluation examples.
Run from the repository root. Default collection is two starter cases.
"""

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def collect(client, case, output):
    repository, number = case["repository"], case["issue_number"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid_repository")
    if not isinstance(number, int) or number <= 0:
        raise ValueError("invalid_issue_number")
    if not re.fullmatch(r"A\d{2}", case["id"]):
        raise ValueError("invalid_case_id")

    async def get(path, params=None):
        for attempt in range(2):
            try:
                response = await client.get(path, params=params)
                if response.status_code >= 500 and attempt == 0:
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.TransportError:
                if attempt == 1:
                    raise
        raise RuntimeError("read_unavailable")

    issue = await get(f"/repos/{repository}/issues/{number}")
    if "pull_request" in issue:
        raise ValueError("pull_request_out_of_scope")
    comments = []
    for page in range(1, 11):
        rows = await get(
            f"/repos/{repository}/issues/{number}/comments", {"per_page": 100, "page": page}
        )
        comments.extend(
            {k: row[k] for k in ("id", "body", "html_url", "created_at", "updated_at")}
            for row in rows
        )
        if len(rows) < 100:
            break
    else:
        raise ValueError("comment_scan_limit")

    selected = {k: issue[k] for k in
        ("number", "title", "body", "html_url", "state", "created_at", "updated_at")}
    content = {"repository": repository, "issue": selected, "comments": comments}
    fingerprint = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    snapshot = {
        "case_id": case["id"], "fetched_at": datetime.now(timezone.utc).isoformat(),
        "reported_comment_count": issue["comments"], "observed_comment_count": len(comments),
        "comment_count_matches_hint": len(comments) == issue["comments"],
        "comment_pagination_completed": True, "content_sha256": fingerprint, "data": content,
        "annotation_status": "pending_human_review",
    }
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{case['id']}-{fingerprint[:12]}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"id": case["id"], "snapshot": str(path), "comments": len(comments),
                      "comment_count_matches_hint": snapshot["comment_count_matches_hint"]}), flush=True)


async def main(args):
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in catalog["cases"]}
    identifiers = list(dict.fromkeys(args.ids))
    if any(identifier not in cases for identifier in identifiers):
        raise SystemExit("unknown_case_id")
    async with httpx.AsyncClient(
        base_url="https://api.github.com", timeout=25,
        headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
                 "User-Agent": "Issue-Agent-ReadOnly-Collector"},
    ) as client:
        for identifier in identifiers:
            try:
                await collect(client, cases[identifier], Path(args.output))
            except httpx.HTTPStatusError as error:
                raise SystemExit(f"{identifier}: github_http_{error.response.status_code}") from None
            except (httpx.HTTPError, ValueError, RuntimeError) as error:
                raise SystemExit(f"{identifier}: {type(error).__name__}") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", default="evals/public-issue-candidates.json")
    parser.add_argument("--ids", nargs="+", default=["A01", "A08"])
    parser.add_argument("--output", default="data/public-issues")
    asyncio.run(main(parser.parse_args()))
