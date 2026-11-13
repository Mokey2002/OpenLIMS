#!/usr/bin/env python3
"""Authorize recovery only from an original release's successful native test jobs."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from publish_release import repository, validate_source, version


def validate_run(run, jobs, commit, selected_repository):
    if (run.get("event") != "release" or run.get("status") != "completed" or run.get("head_sha") != commit
            or run.get("path", "").split("@", 1)[0] != ".github/workflows/installer.yml"
            or run.get("repository", {}).get("full_name", "").lower() != selected_repository.lower()):
        raise RuntimeError("Select the completed original release workflow run for this repository and source commit.")
    required = {"checks": [], "release-gate": [], "amd64": [], "arm64": []}
    for job in jobs:
        name = job.get("name", "")
        key = name if name in ("checks", "release-gate") else None
        matrix = re.fullmatch(r"images \((amd64|arm64), linux/(amd64|arm64), [^)]+\)", name)
        if matrix and matrix[1] == matrix[2]:
            key = matrix[1]
        if key:
            required[key].append(job)
    for name, matches in required.items():
        # Re-running only a failed publisher must retain the earlier successful
        # image jobs. A newer failed native attempt must never use an older pass.
        selected = max(matches, key=lambda job: (job.get("run_attempt", 0), job.get("id", 0))) if matches else {}
        if (selected.get("status") != "completed" or selected.get("conclusion") != "success"
                or selected.get("run_id") != run.get("id")):
            raise RuntimeError(f"Recovery requires a successful original {name} job; image tests and release gates cannot be bypassed.")


def api(endpoint):
    response = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
    return json.loads(response.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=repository, required=True)
    parser.add_argument("--version", type=version, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-directory", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]*", args.run_id):
        parser.error("Select the original numeric release workflow run ID.")
    commit = subprocess.run(["git", "rev-parse", "--verify", f"refs/tags/{args.version}^{{commit}}"],
                            check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "origin/main"], check=True)
    run = api(f"repos/{args.repository}/actions/runs/{args.run_id}")
    response = api(f"repos/{args.repository}/actions/runs/{args.run_id}/jobs?filter=all&per_page=100")
    if response.get("total_count", 0) > 100:
        raise RuntimeError("Original workflow job metadata is incomplete; recovery was not authorized.")
    validate_run(run, response["jobs"], commit, args.repository)
    if args.source_directory.exists():
        raise RuntimeError("Use a fresh source directory; recovery never overwrites an existing checkout.")
    subprocess.run(["git", "worktree", "add", "--detach", str(args.source_directory), commit], check=True)
    validate_source(args.source_directory, args.version, commit)
    print(f"Verified original {args.version} source {commit}, release gates and both native image test jobs.")


if __name__ == "__main__":
    main()
