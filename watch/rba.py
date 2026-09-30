"""Reserve Bank of Australia statistical tables (CSV).

Each RBA CSV has metadata rows (Title, Description, Frequency, Type, Units, Source,
Publication date, Series ID) followed by dated observation rows. Columns are chosen by
keyword so the collector survives small title changes; the chosen title is recorded in
data/_diagnostics.json for checking.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from .common import session

URL = "https://www.rba.gov.au/statistics/tables/csv/{table}-data.csv"
META_ROWS = ("Title", "Description", "Frequency", "Type", "Units", "Source", "Publication date", "Series ID")
DATE_FORMATS = ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%y", "%b-%Y")


def parse_date(text: str) -> date | None:
    text = text.strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(text, f).date()
        except ValueError:
            continue
    return None


def decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1")


def read_table(text: str):
    meta, data = {}, []
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        head = row[0].strip()
        if head in META_ROWS:
            meta[head] = row
            continue
        d = parse_date(head)
        if d:
            data.append((d, row))
    return meta, data


def pick_columns(meta: dict, spec: dict) -> list[int]:
    titles = meta.get("Title", [])
    def cell(name, i):
        r = meta.get(name, [])
        return r[i] if i < len(r) else ""
    inc = [s.lower() for s in spec.get("include", [])]
    any_ = [s.lower() for s in spec.get("include_any", [])]
    exc = [s.lower() for s in spec.get("exclude", [])]
    hits = []
    for i in range(1, len(titles)):
        text = " | ".join(cell(n, i) for n in ("Title", "Description", "Type")).lower()
        if all(s in text for s in inc) and (not any_ or any(s in text for s in any_)) \
                and not any(s in text for s in exc):
            hits.append(i)
    return hits


def collect(cfg: dict):
    s = session()
    start = date.fromisoformat(cfg.get("start", "2015-01-01"))
    rows, notes, errors, tables = [], {}, [], {}
    for spec in cfg["series"]:
        sid, table = spec["id"], spec["table"]
        try:
            if table not in tables:
                resp = s.get(URL.format(table=table), timeout=60)
                resp.raise_for_status()
                tables[table] = read_table(decode(resp.content))
            meta, data = tables[table]
            if "Title" not in meta or not data:
                raise ValueError(f"table {table} did not look like an RBA CSV")
            hits = pick_columns(meta, spec)
            if not hits:
                notes[sid] = {"table": table, "error": "no column matched",
                              "available_titles": meta["Title"][1:60]}
                errors.append(f"{sid}: no column matched in {table}")
                continue
            i = hits[0]
            ids = meta.get("Series ID", [])
            n = 0
            for d, r in data:
                if d < start or i >= len(r) or not r[i].strip():
                    continue
                try:
                    v = float(r[i])
                except ValueError:
                    continue
                rows.append({"series": sid, "period": d.isoformat(), "value": v})
                n += 1
            notes[sid] = {"table": table, "title": meta["Title"][i],
                          "series_id": ids[i] if i < len(ids) else "",
                          "also_matched": [meta["Title"][j] for j in hits[1:4]], "observations": n}
        except Exception as e:  # keep going; one bad series shouldn't stop the others
            errors.append(f"{sid}: {type(e).__name__}: {e}")
    return rows, notes, errors
