"""Descarga las estadísticas públicas del perfil y las guarda en dist/stats.json.

Lo ejecuta la GitHub Action. El panel interactivo (dashboard/index.html) lee
este archivo. Solo usa la biblioteca estándar de Python.

Colaboraciones: se recorren todas las contribuciones desde que se creó la cuenta
y se agrupan los repositorios de otras personas u organizaciones.
  - Repositorio público: se guarda su nombre, enlace y estadísticas.
  - Repositorio privado: NUNCA se guarda su nombre ni su descripción; solo el
    perfil del dueño, cuántos repositorios privados suyos hay y los totales.
Como GitHub no cuenta como "contribución" todos los commits (p. ej. si no eres
colaborador ni has dado estrella o hecho fork del repositorio, o si el commit vive en
tu fork), además se usa la API de búsqueda (commits, PRs e issues de tu autoría) y se
combinan ambas fuentes: así aparece cualquier repositorio aunque tenga un solo commit.
Con el GITHUB_TOKEN de la Action solo se ven los repositorios públicos. Para
incluir los privados hay que guardar un token personal (classic, permisos
"repo" y "read:org") como secreto PERFIL_TOKEN.

Uso:  GITHUB_TOKEN=... python scripts/stats.py <usuario> [archivo_salida]
"""
import json
import os
import sys
import time
import urllib.parse
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


HEADERS = {"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
           "User-Agent": "profile-stats"}


def graphql(query: str, variables: dict, partial: bool = False) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={**HEADERS, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("errors") and not (partial and data.get("data")):
        raise SystemExit(f"Error de GraphQL: {data['errors']}")
    return data["data"]


def rest(path: str) -> dict:
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={**HEADERS, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search_all(kind: str, q: str) -> list:
    """Todos los resultados de una búsqueda (máx. 1000, límite de GitHub)."""
    items = []
    for page in range(1, 11):
        res = rest(f"search/{kind}?q={urllib.parse.quote(q)}&per_page=100&page={page}")
        items += res.get("items", [])
        if len(items) >= res.get("total_count", 0) or not res.get("items"):
            break
        time.sleep(2)  # la búsqueda permite ~30 peticiones por minuto
    return items


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


REPO_FRAGMENT = COLLAB_QUERY[COLLAB_QUERY.index("fragment repo"):]


def add_from_search(login: str, repos: dict) -> None:
    """Completa `repos` con lo que encuentra la búsqueda de GitHub. Por repositorio se
    queda con el mayor conteo de cada fuente, para no contar dos veces lo mismo."""
    found: dict[str, dict] = {}
    try:
        for c in search_all("commits", f"author:{login}"):
            f = found.setdefault(c["repository"]["full_name"], {"commits": 0, "prs": 0, "issues": 0, "dates": []})
            f["commits"] += 1
            f["dates"].append(c["commit"]["author"]["date"][:10])
        for kind, q in (("prs", f"author:{login} type:pr"), ("issues", f"author:{login} type:issue")):
            for i in search_all("issues", q):
                name = i["repository_url"].split("/repos/", 1)[1]
                f = found.setdefault(name, {"commits": 0, "prs": 0, "issues": 0, "dates": []})
                f[kind] += 1
                f["dates"].append(i["created_at"][:10])
    except Exception as err:  # la búsqueda es un complemento: si falla, seguimos sin ella
        print(f"Aviso: no se pudo usar la búsqueda de GitHub ({err})")
        return

    found = {n: f for n, f in found.items() if n.split("/")[0].lower() != login.lower()}
    missing = [n for n in found if n not in repos]
    for i in range(0, len(missing), 50):  # datos completos de los repositorios nuevos
        chunk = missing[i:i + 50]
        fields = "\n".join(f'r{j}: repository(owner: {json.dumps(n.split("/")[0])}, '
                           f'name: {json.dumps(n.split("/")[1])}) {{ ...repo }}'
                           for j, n in enumerate(chunk))
        data = graphql(f"query {{ {fields} }}\n{REPO_FRAGMENT}", {}, partial=True)
        for j, n in enumerate(chunk):
            r = data.get(f"r{j}")
            if r:
                repos[n] = {"repo": r, "commits": 0, "prs": 0, "reviews": 0, "issues": 0,
                            "first": None, "last": None}

    for n, f in found.items():
        e = repos.get(n)
        if not e:
            continue  # sin acceso a sus datos (borrado o privado)
        for k in ("commits", "prs", "issues"):
            e[k] = max(e[k], f[k])
        if f["dates"]:
            e["first"] = min(e["first"] or min(f["dates"]), min(f["dates"]))
            e["last"] = max(e["last"] or max(f["dates"]), max(f["dates"]))


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

    add_from_search(login, repos)

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
