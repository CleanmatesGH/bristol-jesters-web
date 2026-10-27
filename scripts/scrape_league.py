"""Fetch the BADVA league table and save Men's Division 1 to data/league.json.

Runs on a schedule in GitHub Actions (see .github/workflows/league.yml).
Standard library only. The file is only rewritten when the table changes,
and nothing is written if the page can't be read or parsed.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE = "https://badva.org.uk/scripts/table.php"
DIVISION = "Mens Team - Division 1"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "league.json")


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


def main():
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "BristolJestersSite/1.0 (+https://bristoljesters.co.uk)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    teams = parse(html)

    old = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f)
    if old and old.get("teams") == teams:
        print("No change")
        return

    data = {
        "division": "Men's Division 1",
        "season": "2026/27",
        "source": "https://badva.org.uk/",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "teams": teams,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Updated: {len(teams)} teams")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # leave the existing file untouched
        print(f"League update failed: {e}", file=sys.stderr)
        sys.exit(1)
