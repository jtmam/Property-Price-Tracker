"""Valuer-General Victoria: median house prices by suburb (quarterly and annual workbooks).

The download links carry asset IDs that change with every release, so the collector
reads the statistics page, picks the workbook links by their visible text, then finds
the header row (the row with the most period-like cells) and each suburb's row.
"""
from __future__ import annotations

import io
import re
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import pandas as pd

from .common import session

MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
MONTH_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?", re.I)
MONTH_YY_RE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s\-/']*(\d{2})\b", re.I)
YEAR_RE = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")
QTR_RE = re.compile(r"\bq([1-4])\b", re.I)
NOT_A_PERIOD = ("change", "%", "growth", "sales", "no.", "number")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((" ".join("".join(self._text).split()), self._href))
            self._href = None


def workbook_links(html: str, base: str) -> list[tuple[str, str]]:
    p = _Links()
    p.feed(html)
    out = []
    for text, href in p.links:
        if re.search(r"\.xlsx?($|\?)", href, re.I):
            out.append((text, urljoin(base, href)))
    return out


def parse_period(v):
    """Header cell -> ('Q', '2026-Q1') | ('A', '2025') | None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return "Q", f"{v.year}-Q{(v.month - 1) // 3 + 1}"
    if isinstance(v, (int, float)):
        return ("A", str(int(v))) if float(v).is_integer() and 1950 <= v <= 2100 else None
    s = " ".join(str(v).split())
    low = s.lower()
    if not s or any(w in low for w in NOT_A_PERIOD):
        return None
    if re.fullmatch(r"(19|20)\d\d(\.0)?", s):
        return "A", s[:4]
    years = YEAR_RE.findall(s)
    months = [m.lower() for m in MONTH_RE.findall(s)]
    if not years and (m2 := MONTH_YY_RE.search(s)):
        years = ["20" + m2.group(2)]
    if years and (q := QTR_RE.search(low)):
        return "Q", f"{years[-1]}-Q{q.group(1)}"
    if years and months:
        return "Q", f"{years[-1]}-Q{(MONTHS[months[-1][:3]] - 1) // 3 + 1}"
    if len(years) == 1 and not months and re.fullmatch(r"[^\d]*(19|20)\d\d[^\d]*", s):
        return "A", years[0]  # e.g. "2025 (prelim)"
    return None


def to_number(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[$,\s]", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _norm(v) -> str:
    return " ".join(re.sub(r"[^A-Z ]", " ", str(v).upper()).split())


def _cells(grid, i):
    return grid[i] if 0 <= i < len(grid) else []


def find_header(grid):
    """Return (row_index, {col: period}, {col: sales_period_or_None}) or None."""
    best = None
    for i in range(min(len(grid), 60)):
        row, above = _cells(grid, i), _cells(grid, i - 1)
        periods, sales = {}, {}
        # Forward-filled super-header (merged cells above, e.g. "Median" | "No. of sales").
        # Only a row with several filled cells counts, so a lone sheet title such as
        # "Victorian Property Sales Report" is never mistaken for a "sales" block label.
        filled = [j for j, a in enumerate(above) if j > 0 and a is not None
                  and not (isinstance(a, float) and pd.isna(a)) and str(a).strip()]
        sup, last = [""], ""
        for j in range(1, len(row)):
            if len(filled) >= 2 and j in filled:
                last = str(above[j])
            sup.append(last.lower() if len(filled) >= 2 else "")
        month_only = {j for j in filled if MONTH_RE.search(str(above[j])) and not YEAR_RE.search(str(above[j]))}
        month_only_above = month_only if len(month_only) >= 3 else set()
        for j, cell in enumerate(row):
            label = "" if cell is None or (isinstance(cell, float) and pd.isna(cell)) else str(cell)
            combined = f"{sup[j]} {label}".lower()
            if "sales" in combined or "number" in combined:
                p = parse_period(cell) or parse_period(re.sub(r"(?i)\bno\.?(?=\s)|\bnumber\b|\bof\b|\bsales\b", " ", label))
                if p or "sales" in label.lower():
                    sales[j] = p
                continue
            p = parse_period(cell)
            a = above[j] if j < len(above) else None
            a = "" if a is None or (isinstance(a, float) and pd.isna(a)) else str(a)
            # Two-row header: quarter names above ("Jan - Mar"), years below (2026).
            if label and a and (p is None or (j in month_only_above and p[0] == "A")):
                p = parse_period(f"{a} {label}") or p
            if p and p not in periods.values():
                periods[j] = p
        if len(periods) >= 3 and (best is None or len(periods) > len(best[1])):
            best = (i, periods, sales)
    return best


def extract(book: dict[str, pd.DataFrame], suburbs: list[str]):
    """Pull median (and sales count where present) per period for each suburb."""
    wanted = {_norm(s): s for s in suburbs}
    rows, found, sheets = [], set(), []
    for name, df in book.items():
        grid = df.astype(object).where(pd.notna(df), None).values.tolist()
        hdr = find_header(grid)
        if not hdr:
            continue
        h, periods, sales = hdr
        latest = max(periods.values(), key=lambda p: p[1])
        sheets.append(name)
        for r in grid[h + 1:]:
            key = next((_norm(c) for c in r[:3] if c is not None and _norm(c) in wanted), None)
            if not key or wanted[key] in found:
                continue
            suburb = wanted[key]
            found.add(suburb)
            counts = {}
            for j, p in sales.items():
                n = to_number(r[j]) if j < len(r) else None
                if n is not None and 0 <= n < 10000:
                    counts[p or latest] = n
            for j, (freq, period) in periods.items():
                price = to_number(r[j]) if j < len(r) else None
                if price is None or not (50_000 < price < 50_000_000):
                    continue
                rows.append({"suburb": suburb, "freq": freq, "period": period, "median_price": price,
                             "sales_count": counts.get((freq, period))})
    return rows, sorted(set(suburbs) - found), sheets


def collect(cfg: dict, suburbs: list[str]):
    s = session()
    page = s.get(cfg["page"], timeout=60)
    page.raise_for_status()
    links = workbook_links(page.text, cfg["page"])
    rows, notes, missing = [], {"files": {}}, set()
    for f in cfg["files"]:
        want = [t.lower() for t in f["link_text"]]
        match = next(((t, u) for t, u in links if all(w in t.lower() for w in want)), None)
        if not match:
            notes["files"][f["id"]] = {"error": "link not found", "links_on_page": [t for t, _ in links][:30]}
            missing.update(suburbs)
            continue
        text, url = match
        resp = s.get(url, timeout=90)
        resp.raise_for_status()
        book = pd.read_excel(io.BytesIO(resp.content), sheet_name=None, header=None)
        got, miss, sheets = extract(book, suburbs)
        rows += got
        missing.update(miss)
        notes["files"][f["id"]] = {"link_text": text, "url": url, "sheets_used": sheets,
                                   "rows": len(got), "missing_suburbs": miss}
    notes["missing"] = sorted(missing)
    return rows, notes
