#!/usr/bin/env python3
"""Only release a main-branch commit whose complete OpenLIMS CI workflow succeeded."""
import argparse
import json
import re
import subprocess
import time


def successful_run(runs, commit):
    candidates = [run for run in runs if run.get("head_sha") == commit and run.get("event") == "push"
                  and run.get("head_branch") == "main" and run.get("name") == "OpenLIMS CI"]
    if not candidates:
        return False
    selected = max(candidates, key=lambda run: run["id"])
    if selected.get("status") == "completed" and selected.get("conclusion") != "success":
        raise RuntimeError("The latest main-branch CI run for this release commit did not succeed.")
    return selected.get("status") == "completed" and selected.get("conclusion") == "success"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository) or not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        parser.error("Select a repository and complete commit SHA.")
    endpoint = f"repos/{args.repository}/actions/workflows/ci.yml/runs?head_sha={args.commit}&event=push&per_page=100"
    for attempt in range(80):
        response = subprocess.run(["gh", "api", endpoint], check=True, capture_output=True, text=True)
        if successful_run(json.loads(response.stdout)["workflow_runs"], args.commit):
            print("The release commit passed the complete main-branch CI workflow.")
            return
        if attempt == 79:
            raise RuntimeError("Release CI has not completed; rerun after OpenLIMS CI succeeds.")
        print("Waiting for the release commit's main-branch CI run...", flush=True)
        time.sleep(15)


if __name__ == "__main__":
    main()
