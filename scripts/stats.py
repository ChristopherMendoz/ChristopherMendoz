"""Descarga las estadísticas públicas del perfil y las guarda en dist/stats.json.

Lo ejecuta la GitHub Action con el GITHUB_TOKEN del repositorio. El panel
interactivo (dashboard/index.html) lee este archivo. Solo usa la biblioteca
estándar de Python.

Uso:  GITHUB_TOKEN=... python scripts/stats.py <usuario> [archivo_salida]
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOGIN = sys.argv[1]
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "dist/stats.json")

QUERY = """
query($login: String!) {
  user(login: $login) {
    login name avatarUrl url
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, privacy: PUBLIC, isFork: false, first: 100,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      totalCount
      nodes {
        name description url stargazerCount forkCount pushedAt
        primaryLanguage { name color }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def graphql(query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Content-Type": "application/json",
                 "User-Agent": "profile-stats"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors"):
        raise SystemExit(f"Error de GraphQL: {data['errors']}")
    return data["data"]


def main() -> None:
    u = graphql(QUERY, {"login": LOGIN})["user"]
    cc = u["contributionsCollection"]
    calendar = [{"date": d["date"], "count": d["contributionCount"]}
                for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]

    langs: dict[str, dict] = {}
    repos = []
    for r in u["repositories"]["nodes"]:
        for e in r["languages"]["edges"]:
            n = e["node"]["name"]
            langs.setdefault(n, {"name": n, "color": e["node"]["color"], "bytes": 0, "repos": 0})
            langs[n]["bytes"] += e["size"]
            langs[n]["repos"] += 1
        repos.append({
            "name": r["name"], "description": r["description"], "url": r["url"],
            "stars": r["stargazerCount"], "forks": r["forkCount"], "pushed": r["pushedAt"],
            "language": (r["primaryLanguage"] or {}).get("name"),
            "color": (r["primaryLanguage"] or {}).get("color"),
            "languages": [e["node"]["name"] for e in r["languages"]["edges"]],
        })

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "user": {"login": u["login"], "name": u["name"], "avatar": u["avatarUrl"], "url": u["url"],
                 "followers": u["followers"]["totalCount"], "public_repos": u["repositories"]["totalCount"]},
        "totals": {"contributions": cc["contributionCalendar"]["totalContributions"],
                   "commits": cc["totalCommitContributions"],
                   "prs": cc["totalPullRequestContributions"],
                   "reviews": cc["totalPullRequestReviewContributions"],
                   "issues": cc["totalIssueContributions"],
                   "private": cc["restrictedContributionsCount"]},
        "calendar": calendar,
        "languages": sorted(langs.values(), key=lambda l: -l["bytes"]),
        "repos": repos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Generado {OUT}: {len(calendar)} días, {len(repos)} repositorios, {len(langs)} lenguajes")


if __name__ == "__main__":
    main()
