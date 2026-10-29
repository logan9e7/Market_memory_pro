#!/usr/bin/env python3
"""Gate a Render deploy hook on both successful CI workflows for current main.

Only reads GitHub metadata. Prints exactly "true" or "false" to stdout;
errors go to stderr and fail the workflow.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.github.com"
REPO = os.environ.get("REPOSITORY", "")
SHA = os.environ.get("RELEASE_SHA", "")
TOKEN = os.environ.get("GH_TOKEN", "")


def get_json(path):
    request = urllib.request.Request(
        BASE + path,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
            "User-Agent": "MarketMemoryVerifiedDeploy/1",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def gate():
    if not TOKEN or not REPO or len(SHA) != 40 or "/" not in REPO:
        raise RuntimeError("Missing GitHub release gate context")
    # A newer merge supersedes this release; never deploy stale code.
    main = get_json(f"/repos/{REPO}/commits/main")
    if main["sha"] != SHA:
        return False
    for attempt in range(20):
        runs = get_json(
            f"/repos/{REPO}/actions/workflows/hybrid-quant.yml/runs"
            "?branch=main&per_page=30"
        )["workflow_runs"]
        matches = [r for r in runs if r["head_sha"] == SHA and r["event"] == "push"]
        if any(r["conclusion"] == "success" for r in matches):
            return True
        if any(r["conclusion"] in ("failure", "cancelled", "timed_out") for r in matches):
            raise RuntimeError("Matching native C++ checks did not pass")
        if attempt < 19:
            time.sleep(15)
    raise RuntimeError("Matching native C++ checks did not complete in time")


if __name__ == "__main__":
    try:
        print("true" if gate() else "false")
    except Exception as exc:
        print(f"Release gate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
