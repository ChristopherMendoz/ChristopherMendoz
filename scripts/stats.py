"""Descarga las estadísticas públicas del perfil y las guarda en dist/stats.json.

Lo ejecuta la GitHub Action. El panel interactivo (dashboard/index.html) lee
este archivo. Solo usa la biblioteca estándar de Python.

Colaboraciones: se recorren todas las contribuciones desde que se creó la cuenta
y se agrupan los repositorios de otras personas u organizaciones.
  - Repositorio público: se guarda su nombre, enlace y estadísticas.
  - Repositorio privado: NUNCA se guarda su nombre ni su descripción; solo el
    perfil del dueño, cuántos repositorios privados suyos hay y los totales.
Con el GITHUB_TOKEN de la Action solo se ven los repositorios públicos. Para
incluir los privados hay que guardar un token personal (classic, permisos
"repo" y "read:org") como secreto PERFIL_TOKEN.

Uso:  GITHUB_TOKEN=... python scripts/stats.py <usuario> [archivo_salida]
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGIN = sys.argv[1]
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "dist/stats.json")

QUERY = """
query($login: String!) {
  user(login: $login) {
    login name avatarUrl url createdAt
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


COLLAB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      commitContributionsByRepository(maxRepositories: 100) {
        repository { ...repo }
        contributions(first: 100) { nodes { occurredAt commitCount } }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository { ...repo } contributions { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { ...repo } contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 100) {
        repository { ...repo } contributions { totalCount }
      }
    }
  }
}
fragment repo on Repository {
  nameWithOwner name description url isPrivate stargazerCount forkCount
  primaryLanguage { name color }
  owner { __typename login avatarUrl url }
}
"""


def periods(start: datetime, end: datetime):
    """Tramos de 90 días: así cada repositorio tiene como mucho 90 días con commits por
    tramo y la lista de 100 nodos nunca se queda corta."""
    a = start
    while a < end:
        b = min(a + timedelta(days=90), end)
        yield a, b
        a = b


def collaborations(login: str, created: str) -> dict:
    start = datetime.fromisoformat(created.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    repos: dict[str, dict] = {}
    restricted = 0
    kinds = {"commitContributionsByRepository": "commits",
             "pullRequestContributionsByRepository": "prs",
             "pullRequestReviewContributionsByRepository": "reviews",
             "issueContributionsByRepository": "issues"}

    for a, b in periods(start, now):
        cc = graphql(COLLAB_QUERY, {"login": login, "from": a.isoformat(), "to": b.isoformat()})[
            "user"]["contributionsCollection"]
        restricted += cc["restrictedContributionsCount"]
        for field, kind in kinds.items():
            for item in cc[field]:
                r = item["repository"]
                if r["owner"]["login"].lower() == login.lower():
                    continue  # repositorio propio: no es colaboración
                e = repos.setdefault(r["nameWithOwner"], {
                    "repo": r, "commits": 0, "prs": 0, "reviews": 0, "issues": 0,
                    "first": None, "last": None})
                if kind == "commits":
                    for n in item["contributions"]["nodes"]:
                        e["commits"] += n["commitCount"]
                        d = n["occurredAt"][:10]
                        e["first"] = min(e["first"] or d, d)
                        e["last"] = max(e["last"] or d, d)
                else:
                    e[kind] += item["contributions"]["totalCount"]

    public, owners = [], {}
    for e in repos.values():
        r, o = e["repo"], e["repo"]["owner"]
        stats = {k: e[k] for k in ("commits", "prs", "reviews", "issues", "first", "last")}
        owner = {"login": o["login"], "avatar": o["avatarUrl"], "url": o["url"],
                 "type": "org" if o["__typename"] == "Organization" else "user"}
        if r["isPrivate"]:
            # Solo el perfil del dueño y los totales; nada del repositorio.
            g = owners.setdefault(o["login"], {"owner": owner, "repos": 0, "commits": 0, "prs": 0,
                                               "reviews": 0, "issues": 0, "first": None, "last": None})
            g["repos"] += 1
            for k in ("commits", "prs", "reviews", "issues"):
                g[k] += stats[k]
            for k, f in (("first", min), ("last", max)):
                if stats[k]:
                    g[k] = f(g[k] or stats[k], stats[k])
        else:
            public.append({"name": r["name"], "full_name": r["nameWithOwner"], "url": r["url"],
                           "description": r["description"], "stars": r["stargazerCount"],
                           "forks": r["forkCount"],
                           "language": (r["primaryLanguage"] or {}).get("name"),
                           "color": (r["primaryLanguage"] or {}).get("color"),
                           "owner": owner, **stats})

    total = lambda e: e["commits"] + e["prs"] + e["reviews"] + e["issues"]
    public.sort(key=lambda e: -total(e))
    private = sorted(owners.values(), key=lambda e: -total(e))
    people = {e["owner"]["login"] for e in public} | set(owners)
    return {
        "includes_private": os.environ.get("PRIVATE_ACCESS") == "1",
        "since": start.date().isoformat(),
        "public": public,
        "private": private,
        "restricted": restricted,
        "totals": {
            "repos": len(public) + sum(e["repos"] for e in private),
            "public_repos": len(public),
            "private_repos": sum(e["repos"] for e in private),
            "owners": len(people),
            **{k: sum(e[k] for e in public) + sum(e[k] for e in private)
               for k in ("commits", "prs", "reviews", "issues")},
        },
    }


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
        "collabs": collaborations(u["login"], u["createdAt"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Generado {OUT}: {len(calendar)} días, {len(repos)} repositorios, {len(langs)} lenguajes, "
          f"{out['collabs']['totals']['repos']} repositorios en colaboración")


if __name__ == "__main__":
    main()
