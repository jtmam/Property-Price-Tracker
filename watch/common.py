"""Shared helpers: HTTP session, tidy CSV storage with change detection, diagnostics."""
from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CHANGES = DATA / "changes.csv"
CHANGE_COLS = ["detected_on", "dataset", "series", "period", "old", "new", "kind"]

USER_AGENT = "Mozilla/5.0 (compatible; melb-property-watch/1.0; personal market research)"


def session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = USER_AGENT
    return s


def fmt(v) -> str:
    """Stable text form for a value so CSV diffs stay clean (1450000 not 1450000.0)."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v == "":
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v).strip()
    if math.isnan(f):
        return ""
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else f"{round(f, 4):g}"


def upsert(dataset: str, rows: list[dict], key_cols: list[str], value_cols: list[str],
           series_col: str) -> dict:
    """Merge fresh rows into data/<dataset>.csv, keeping history the source no longer shows.

    Logs new observations and revisions to data/changes.csv. The very first run, and the
    first rows of any series added later, are logged as a single "baseline" line instead.
    """
    path = DATA / f"{dataset}.csv"
    cols = key_cols + value_cols
    fresh = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
    for c in cols:
        fresh[c] = fresh[c].map(fmt)
    fresh = fresh.drop_duplicates(subset=key_cols, keep="last")

    baseline = not path.exists()
    old = pd.DataFrame(columns=cols) if baseline else pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in cols:
        if c not in old.columns:
            old[c] = ""

    old_idx = {tuple(r[k] for k in key_cols): r for r in old[cols].to_dict("records")}
    known = set(old[series_col]) if series_col in old.columns else set()
    changes, n_new, n_rev, added = [], 0, 0, {}
    today = date.today().isoformat()
    main_val = value_cols[0]
    for r in fresh.to_dict("records"):
        k = tuple(r[c] for c in key_cols)
        prev = old_idx.get(k)
        if prev is None:
            n_new += 1
            if not baseline and r[series_col] not in known:     # a series seen for the first time
                added[r[series_col]] = added.get(r[series_col], 0) + 1
                old_idx[k] = r
                continue
            col, kind, before = main_val, "new", ""
        else:
            for c in value_cols:            # a blank in the fresh pull never erases history
                if r[c] == "":
                    r[c] = prev[c]
            diff = [c for c in value_cols if prev[c] != r[c]]
            if not diff:
                continue
            n_rev += 1
            col = diff[0]
            kind = "revised" if col == main_val else f"revised {col}"
            before = prev[col]
        changes.append({"detected_on": today, "dataset": dataset, "series": r[series_col],
                        "period": r.get("period", ""), "old": before, "new": r[col], "kind": kind})
        old_idx[k] = r

    merged = pd.DataFrame(list(old_idx.values()), columns=cols).sort_values(key_cols)
    DATA.mkdir(exist_ok=True)
    merged.to_csv(path, index=False)

    if baseline:
        changes = [{"detected_on": today, "dataset": dataset, "series": "all", "period": "",
                    "old": "", "new": str(len(merged)), "kind": "baseline"}]
    changes += [{"detected_on": today, "dataset": dataset, "series": s, "period": "",
                 "old": "", "new": str(n), "kind": "baseline"} for s, n in added.items()]
    if changes:
        log = pd.read_csv(CHANGES, dtype=str, keep_default_na=False) if CHANGES.exists() \
            else pd.DataFrame(columns=CHANGE_COLS)
        log = pd.concat([log, pd.DataFrame(changes, columns=CHANGE_COLS)], ignore_index=True)
        log.to_csv(CHANGES, index=False)
    return {"rows": len(merged), "new": n_new, "revised": n_rev, "baseline": baseline}


def write_diagnostics(diag: dict) -> None:
    """Per-source status without timestamps, so the file only changes when something real does."""
    DATA.mkdir(exist_ok=True)
    (DATA / "_diagnostics.json").write_text(json.dumps(diag, indent=2, sort_keys=True) + "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = ["| Source | Status | Detail |", "|---|---|---|"]
    for name, d in diag.items():
        detail = d.get("message") or ", ".join(f"{k}: {v}" for k, v in d.get("counts", {}).items()) \
            or f"{len(d.get('notes', {}))} series read"
        lines.append(f"| {name} | {d.get('status')} | {detail} |")
    text = "\n".join(lines)
    print(text)
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Collection run\n\n" + text + "\n")
