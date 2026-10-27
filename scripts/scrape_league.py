"""Fetch BADVA data for the website.

- League table (Men's Division 1) -> data/league.json
- Bristol Jesters match results (scores and set scores) -> data/results.json


Runs on a schedule in GitHub Actions (see .github/workflows/league.yml).
Standard library only. The file is only rewritten when the table changes,
and nothing is written if the page can't be read or parsed.
"""
import json
import re
import urllib.parse
import os
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE = "https://badva.org.uk/scripts/table.php"
DIVISION = "Mens Team - Division 1"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "league.json")
FIXTURES = "https://badva.org.uk/scripts/fixtures.php?fieldset=FFFFFF&team=&outside=0"
SEASON = "2026/27"
TEAM_ID = "547"   # Bristol Jesters on BADVA
RESULTS_OUT = os.path.join(os.path.dirname(__file__), "..", "data", "results.json")
UA = {"User-Agent": "BristolJestersSite/1.0 (+https://bristoljesters.co.uk)"}


class TableParser(HTMLParser):
    """Collects every table.idTable that follows a division heading."""

    def __init__(self):
        super().__init__()
        self.tables = {}          # heading -> list of rows (list of cell text)
        self.heading = None
        self.in_heading = False
        self.current = None
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "p" and "headerFormCz" in (a.get("class") or ""):
            self.in_heading, self.heading = True, ""
        elif tag == "table" and "idTable" in (a.get("class") or "") and self.heading:
            self.current = self.tables.setdefault(self.heading.strip(), [])
        elif tag == "tr" and self.current is not None:
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = ""

    def handle_endtag(self, tag):
        if tag == "p" and self.in_heading:
            self.in_heading = False
        elif tag == "td" and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.current.append(self.row)
            self.row = None
        elif tag == "table" and self.current is not None:
            self.current = None

    def handle_data(self, data):
        if self.in_heading:
            self.heading += data
        elif self.cell is not None:
            self.cell += data


def parse(html):
    p = TableParser()
    p.feed(html)
    rows = p.tables.get(DIVISION)
    if not rows:
        raise ValueError(f"'{DIVISION}' not found on the page")
    teams = []
    for r in rows:
        if len(r) < 12 or not r[0].rstrip(".").isdigit():
            continue  # header row or anything unexpected
        teams.append({
            "pos": int(r[0].rstrip(".")),
            "team": r[1],
            "pts": int(r[2]),
            "played": int(r[3]),
            "won": int(r[4]),
            "lost": int(r[5]),
            "setsFor": int(r[6]),
            "setsAgainst": int(r[8]),
            "pointsFor": int(r[9]),
            "pointsAgainst": int(r[11]),
        })
    if len(teams) < 2:
        raise ValueError(f"only {len(teams)} teams parsed")
    return teams


class RowParser(HTMLParser):
    """Collects the text of every table cell, row by row."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = ""

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append(" ".join(self.cell.split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data


MATCH = re.compile(r"^MnD1-0*(\d+)\s+(.+?)\s+vs\.\s+(.+)$")
SETS = re.compile(r"(\d+)\s*:\s*(\d+)")


def parse_results(html):
    p = RowParser()
    p.feed(html)
    out = {}
    for r in p.rows:
        if len(r) < 3:
            continue
        m = MATCH.match(r[0])
        if not m:
            continue
        code, home, away = m.group(1), m.group(2).strip(), m.group(3).strip()
        inner = r[2][r[2].find("(") + 1:r[2].rfind(")")] if "(" in r[2] else ""
        sets = [[int(a), int(b)] for a, b in SETS.findall(inner)]
        if not sets:
            continue  # not played yet (shown as 0:0)
        out[code] = {"home": home, "away": away, "ref": r[1].replace("ref:", "").strip(), "sets": sets}
    return out


def fetch(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def save(path, key, value, extra):
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    if old and old.get(key) == value:
        return False
    data = dict(extra)
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data[key] = value
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return True


def update_table():
    teams = parse(fetch(SOURCE))
    changed = save(OUT, "teams", teams, {"division": "Men's Division 1", "season": SEASON, "source": "https://badva.org.uk/"})
    print("League table:", "updated" if changed else "no change", f"({len(teams)} teams)")


def update_results():
    results = parse_results(fetch(FIXTURES, {"cSeason": SEASON, "cTeam": TEAM_ID}))
    changed = save(RESULTS_OUT, "matches", results, {"team": "Bristol Jesters", "season": SEASON, "source": "https://badva.org.uk/fixtures.html"})
    print("Results:", "updated" if changed else "no change", f"({len(results)} played)")


def main():
    failed = 0
    for job in (update_table, update_results):
        try:
            job()
        except Exception as e:  # keep the existing file for this job
            failed += 1
            print(f"{job.__name__} failed: {e}", file=sys.stderr)
    sys.exit(1 if failed == 2 else 0)


if __name__ == "__main__":
    main()
