"""Regenerate the auto-updated sections of README.md.

Fills the block between <!-- latest:start --> and <!-- latest:end --> with the
most recently pushed public, non-fork repositories (last 180 days) and each one's latest commit.
Stdlib only so the workflow needs no install step. Uses GITHUB_TOKEN when set.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "chadlipscomb")
LIMIT = 5
# Older pushes make the profile look stale rather than active
MAX_AGE = timedelta(days=180)
README = Path(__file__).parent / "README.md"
API = "https://api.github.com"


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def latest_pushes():
    repos = get(f"/users/{USER}/repos?type=owner&sort=pushed&per_page=50")
    repos = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] != USER]
    lines = []
    for repo in repos[:LIMIT]:
        commits = get(f"/repos/{USER}/{repo['name']}/commits?per_page=1")
        if not commits:
            continue
        commit = commits[0]
        message = commit["commit"]["message"].splitlines()[0].strip()
        if len(message) > 72:
            message = message[:69].rstrip() + "…"
        # Escape characters that would break inline markdown
        message = re.sub(r"([\\`*_\[\]<>|])", r"\\\1", message)
        when = datetime.fromisoformat(commit["commit"]["committer"]["date"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - when > MAX_AGE:
            continue
        lines.append(
            f"- [**{repo['name']}**]({repo['html_url']}): "
            f"[{message}]({commit['html_url']}) · {when:%b %-d, %Y}"
        )
    return "\n".join(lines) or "_Nothing public in the last few months._"


def replace_block(text, name, body):
    pattern = re.compile(rf"(<!-- {name}:start -->).*?(<!-- {name}:end -->)", re.DOTALL)
    if not pattern.search(text):
        sys.exit(f"marker {name} not found in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", text)


def main():
    text = README.read_text()
    updated = replace_block(text, "latest", latest_pushes())
    if updated != text:
        README.write_text(updated)
        print("README.md updated")
    else:
        print("README.md unchanged")


if __name__ == "__main__":
    main()
