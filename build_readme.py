"""Regenerate the auto-updated parts of the profile.

Fills the block between <!-- latest:start --> and <!-- latest:end --> in README.md with the
most recently pushed public, non-fork repositories (last 180 days) and each one's latest commit,
and redraws languages.svg from the public, non-fork repositories' language byte counts.
Stdlib only so the workflow needs no install step. Uses GITHUB_TOKEN when set.
"""

import json
import os
import re
import sys
import urllib.request
from html import escape
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = os.environ.get("PROFILE_USER", "chadlipscomb")
LIMIT = 5
# Older pushes make the profile look stale rather than active
MAX_AGE = timedelta(days=180)
README = Path(__file__).parent / "README.md"
LANGUAGES_SVG = Path(__file__).parent / "languages.svg"
API = "https://api.github.com"

# Most of my code lives in client repositories, so GitHub never sees it. These lead the card,
# labelled as such, ahead of the measured public-repo breakdown.
PRIMARY_LANGUAGES = ["PowerShell", "Terraform"]
IGNORED_LANGUAGES = {"HTML", "CSS", "SCSS", "Dockerfile", "Makefile", "CMake"}
LANGUAGE_LIMIT = 8
# GitHub linguist colors, except PowerShell, whose linguist navy vanishes on a dark background
COLORS = {
    "PowerShell": "#5391fe",
    "Terraform": "#844fba",
    "HCL": "#844fba",
    "Python": "#3572a5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Shell": "#89e051",
    "Jinja": "#a52a22",
    "C#": "#178600",
    "C++": "#f34b7d",
    "C": "#555555",
    "Go": "#00add8",
    "Swift": "#f05138",
    "YAML": "#cb171e",
}


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


def public_language_bytes():
    repos = get(f"/users/{USER}/repos?type=owner&per_page=100")
    totals = {}
    for repo in repos:
        if repo["fork"] or repo["name"] == USER:
            continue
        for language, size in get(f"/repos/{USER}/{repo['name']}/languages").items():
            if language not in IGNORED_LANGUAGES:
                totals[language] = totals.get(language, 0) + size
    return totals


def languages_svg(totals):
    total = sum(totals.values()) or 1
    measured = sorted(totals.items(), key=lambda kv: -kv[1])[:LANGUAGE_LIMIT]
    width, pad = 495, 20
    inner = width - 2 * pad
    out = []

    def text(x, y, body, cls, anchor="start"):
        out.append(f'<text x="{x}" y="{y}" class="{cls}" text-anchor="{anchor}">{escape(body)}</text>')

    def dot(x, y, language):
        out.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{COLORS.get(language, "#8b949e")}"/>')

    text(pad, 28, "Most-used languages", "title")
    text(pad, 56, "Day to day, in client and government repositories (not public)", "label")
    x = pad
    for language in PRIMARY_LANGUAGES:
        dot(x + 5, 76, language)
        text(x + 16, 80, language, "name strong")
        x += 16 + 9 * len(language) + 24
    text(pad, 114, "Public GitHub repositories", "label")
    x = pad
    out.append(f'<clipPath id="bar"><rect x="{pad}" y="124" width="{inner}" height="8" rx="4"/></clipPath>')
    out.append('<g clip-path="url(#bar)">')
    for language, size in measured:
        w = inner * size / total
        out.append(f'<rect x="{x:.1f}" y="124" width="{w + 0.5:.1f}" height="8" fill="{COLORS.get(language, "#8b949e")}"/>')
        x += w
    out.append("</g>")
    column = inner / 2
    for i, (language, size) in enumerate(measured):
        cx = pad + (i % 2) * column
        cy = 156 + (i // 2) * 24
        dot(cx + 5, cy - 4, language)
        text(cx + 16, cy, language, "name")
        text(cx + column - 12, cy, f"{100 * size / total:.1f}%", "pct", "end")
    height = 156 + ((len(measured) + 1) // 2) * 24
    style = (
        "text{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}"
        ".title{font-size:16px;font-weight:600;fill:#0969da}"
        ".label{font-size:12px;fill:#59636e}"
        ".name{font-size:14px;fill:#1f2328}"
        ".pct{font-size:13px;fill:#59636e}"
        ".strong{font-weight:600}"
        "@media (prefers-color-scheme:dark){.title{fill:#4fb3bf}.label,.pct{fill:#9198a1}.name{fill:#e6edf3}}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Most-used languages">'
        f"<style>{style}</style>" + "".join(out) + "</svg>\n"
    )


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
    svg = languages_svg(public_language_bytes())
    if not LANGUAGES_SVG.exists() or LANGUAGES_SVG.read_text() != svg:
        LANGUAGES_SVG.write_text(svg)
        print("languages.svg updated")


if __name__ == "__main__":
    main()
