"""Build the dashboard page from the CSVs in data/.

Writes docs/index.html (a full page for GitHub Pages) and dashboard/artifact.html (the same
page as a fragment, for publishing as a private Claude artifact). The page holds data only,
never a build timestamp, so the files change only when the data does.

    python build_dashboard.py                          # after collect.py
    python build_dashboard.py --commentary read.md     # adds the weekly written read
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COLORS = ["--s1", "--s2", "--s3", "--s4"]
SOURCES = {"vgv": "Valuer-General", "rba": "RBA", "abs": "ABS"}
MACRO_ORDER = ["cash_rate_target", "mortgage_rate_all", "inflation", "unemployment_vic", "unemployment_au",
               "housing_credit"]


def point(period: str):
    """Period text -> (decimal year for plotting, long label, short tick label)."""
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", period):
        y, mo = int(m[1]), int(m[2]) * 3
        return y + (mo - 0.5) / 12, f"{MONTHS[mo - 1]} qtr {y}", f"{MONTHS[mo - 1]} {str(y)[2:]}"
    if re.fullmatch(r"\d{4}", period):
        return float(period), period, period
    d = date.fromisoformat(period)
    days = 366 if calendar.isleap(d.year) else 365
    return d.year + (d.timetuple().tm_yday - 0.5) / days, f"{MONTHS[d.month - 1]} {d.year}", \
        f"{MONTHS[d.month - 1]} {str(d.year)[2:]}"


def read_csv(path: Path):
    return pd.read_csv(path, dtype=str, keep_default_na=False) if path.exists() else None


def money(v) -> str:
    return f"${float(v):,.0f}"


def parse_commentary(path: Path):
    text = path.read_text().strip()
    when = date.today().isoformat()
    if m := re.match(r"(?i)date:\s*(\d{4}-\d{2}-\d{2})\s*\n", text):
        when, text = m[1], text[m.end():]
    blocks = []
    for chunk in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in chunk.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if all(re.match(r"[-*] ", ln) for ln in lines):
            blocks.append({"type": "list", "items": [ln[2:].strip() for ln in lines]})
        else:
            blocks.append({"type": "p", "text": " ".join(lines)})
    return {"date": when, "blocks": blocks}


def change_feed(ch: pd.DataFrame | None, macro_meta: dict, limit: int = 25) -> list[dict]:
    """Readable 'what changed' items. Seasonal re-estimation revises many old values at once,
    so a burst of revisions for one series collapses into a single line."""
    if ch is None or ch.empty:
        return []
    groups = defaultdict(lambda: {"new": [], "rev": [], "base": []})
    order = []
    for r in ch.itertuples(index=False):
        k = (r.detected_on, r.dataset, r.series)
        if k not in groups:
            order.append(k)
        bucket = "base" if r.kind == "baseline" else "new" if r.kind == "new" else "rev"
        groups[k][bucket].append(r)

    def name_value(dataset, series, value):
        if dataset == "sales_medians":
            return f"{series} median house", money(value)
        m = macro_meta.get(series, {"label": series, "decimals": 2})
        return m["label"], f"{float(value):.{m['decimals']}f}%"

    items = []
    for k in sorted(order, key=lambda k: k[0], reverse=True):
        day, dataset, series = k
        g = groups[k]
        for r in g["base"]:
            if series == "all":
                what = "suburb sale prices" if dataset == "sales_medians" else "rates and economic data"
            else:
                what = name_value(dataset, series, 0)[0]
            items.append({"date": day, "text": f"Baseline collected: {r.new} records of {what}.", "was": ""})
        new = sorted(g["new"], key=lambda r: point(r.period)[0], reverse=True)
        if len(new) > 3:
            label, _ = name_value(dataset, series, new[0].new or 0)
            items.append({"date": day, "text": f"{label}: {len(new)} new values, latest {point(new[0].period)[1]}.",
                          "was": ""})
        else:
            for r in new:
                label, val = name_value(dataset, series, r.new)
                items.append({"date": day, "text": f"{label}, {point(r.period)[1]}: {val}", "was": ""})
        revs = g["rev"]
        if len(revs) > 2:
            label, _ = name_value(dataset, series, 0)
            items.append({"date": day, "text": f"{label}: {len(revs)} earlier values revised.", "was": ""})
        else:
            for r in revs:
                label, val = name_value(dataset, series, r.new)
                extra = "" if r.kind == "revised" else f", {r.kind.replace('revised ', '').replace('_', ' ')} revised"
                was = f"was {name_value(dataset, series, r.old)[1]}" if r.old and r.kind == "revised" else ""
                items.append({"date": day, "text": f"{label}, {point(r.period)[1]}: {val}{extra}", "was": was})
    return items[:limit]


def build(data_dir: Path, out_dir: Path, commentary: Path | None = None) -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    subs = [{"name": s["name"], "color": COLORS[i % len(COLORS)]} for i, s in enumerate(cfg["suburbs"])]
    tgt = cfg["target"]
    beds = sorted(tgt.get("bedrooms", []))
    bed_txt = " and ".join(f"{b}+" if b == beds[-1] and b >= 4 else str(b) for b in beds)
    target = f"{tgt['property_type'].capitalize()}s, {bed_txt} bedrooms" if beds else f"{tgt['property_type'].capitalize()}s"

    sales = {"quarterly": {}, "annual": {}}
    sm = read_csv(data_dir / "sales_medians.csv")
    for s in subs:
        for freq, kind in (("Q", "quarterly"), ("A", "annual")):
            pts = []
            if sm is not None:
                rows = sm[(sm.suburb == s["name"]) & (sm.freq == freq) & (sm.median_price != "")]
                for r in rows.itertuples(index=False):
                    x, lab, short = point(r.period)
                    n = int(float(r.sales_count)) if r.sales_count else None
                    pts.append([round(x, 4), float(r.median_price), lab, short, n])
            sales[kind][s["name"]] = sorted(pts)

    series_cfg = cfg["sources"]["rba"]["series"] + cfg["sources"].get("abs", {}).get("series", [])
    series_cfg.sort(key=lambda sc: MACRO_ORDER.index(sc["id"]) if sc["id"] in MACRO_ORDER else 99)
    mc = read_csv(data_dir / "macro.csv")
    macro, meta = [], {}
    for sc in series_cfg:
        pts = []
        if mc is not None:
            for r in mc[(mc.series == sc["id"]) & (mc.value != "")].itertuples(index=False):
                x, lab, short = point(r.period)
                pts.append([round(x, 4), float(r.value), lab, short])
        m = {"id": sc["id"], "label": sc["label"], "decimals": sc.get("decimals", 2), "points": sorted(pts)}
        macro.append(m)
        meta[sc["id"]] = m

    ch = read_csv(data_dir / "changes.csv")
    diag_path = data_dir / "_diagnostics.json"
    diag = json.loads(diag_path.read_text()) if diag_path.exists() else {}
    data = {
        "target": target,
        "suburbs": subs,
        "sales": sales,
        "macro": macro,
        "changes": change_feed(ch, meta),
        "status": [{"name": n, "status": diag.get(k, {}).get("status", "pending")} for k, n in SOURCES.items()],
        "watchlist": cfg.get("watchlist", []),
        "data_last_changed": ch.detected_on.max() if ch is not None and not ch.empty else None,
        "commentary": parse_commentary(commentary) if commentary else None,
    }

    tpl = (ROOT / "dashboard" / "template.html").read_text()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    head, body = tpl.replace("__DATA__", payload).split("<!--BODY-->", 1)
    (out_dir / "docs").mkdir(parents=True, exist_ok=True)
    (out_dir / "dashboard").mkdir(parents=True, exist_ok=True)
    (out_dir / "docs" / ".nojekyll").write_text("")
    (out_dir / "docs" / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{head}</head>\n<body>\n{body}</body>\n</html>\n")
    (out_dir / "dashboard" / "artifact.html").write_text(head + body)
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--out-dir", type=Path, default=ROOT)
    ap.add_argument("--commentary", type=Path)
    a = ap.parse_args()
    d = build(a.data_dir, a.out_dir, a.commentary)
    print(f"Built dashboard: {sum(len(v) for v in d['sales']['quarterly'].values())} quarterly points, "
          f"{sum(len(m['points']) for m in d['macro'])} macro points, {len(d['changes'])} change items.")
