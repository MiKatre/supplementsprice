"""Facts read from product pages (protein per 100 g, net weight, third-party testing) change rarely.
Remember them per product URL so a nightly run only opens pages it hasn't seen in a month."""

import json
from datetime import date, timedelta
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "enrich.json"
MAX_AGE = timedelta(days=30)


class Enrich:
    def __init__(self, path: Path = PATH):
        self.path = path
        self.data: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, url: str) -> dict | None:
        facts = self.data.get(url)
        if not facts or date.fromisoformat(facts["checked"]) < date.today() - MAX_AGE:
            return None
        return facts

    def put(self, url: str, **facts) -> dict:
        self.data[url] = {**facts, "checked": date.today().isoformat()}
        return self.data[url]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=0, sort_keys=True) + "\n")


ENRICH = Enrich()
