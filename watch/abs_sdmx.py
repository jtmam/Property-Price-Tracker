"""Australian Bureau of Statistics Data API (SDMX REST, CSV with labels)."""
from __future__ import annotations

import calendar
import io
import re

import pandas as pd

from .common import session

URL = "https://data.api.abs.gov.au/rest/data/{flow}/{key}"


def period_to_date(p: str) -> str:
    """'2026-08' -> '2026-08-31', '2026-Q2' -> '2026-06-30', '2025' -> '2025-12-31'."""
    p = str(p).split(":")[0].strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m:
        y, mo = int(m[1]), int(m[2])
    elif (m := re.fullmatch(r"(\d{4})-Q([1-4])", p)):
        y, mo = int(m[1]), int(m[2]) * 3
    elif re.fullmatch(r"\d{4}", p):
        y, mo = int(p), 12
    else:
        return p
    return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"


def _col(df: pd.DataFrame, name: str) -> str:
    for c in df.columns:
        if c.split(":")[0].strip().upper() == name:
            return c
    raise KeyError(f"{name} column missing; got {list(df.columns)[:12]}")


def collect(cfg: dict):
    s = session()
    rows, notes, errors = [], {}, []
    for spec in cfg.get("series", []):
        sid = spec["id"]
        try:
            resp = s.get(URL.format(flow=spec["flow"], key=spec["key"]), timeout=90,
                         params={"startPeriod": spec.get("start", "2015-01"), "format": "csvfilewithlabels"})
            if resp.status_code == 404:
                raise ValueError("no data returned (404): the flow or key in config.yaml needs checking")
            resp.raise_for_status()
            df = pd.read_csv(io.BytesIO(resp.content), dtype=str, keep_default_na=False)
            tcol, vcol = _col(df, "TIME_PERIOD"), _col(df, "OBS_VALUE")
            dims = [c for c in df.columns if c not in (tcol, vcol) and df[c].nunique() > 1]
            note = {"flow": spec["flow"], "key": spec["key"]}
            if dims:  # key matched several series; keep the first and record what else came back
                first = df.iloc[0]
                note["warning"] = "key matched several series; using the first"
                note["varying"] = {c: sorted(df[c].unique())[:8] for c in dims}
                for c in dims:
                    df = df[df[c] == first[c]]
            n = 0
            for t, v in zip(df[tcol], df[vcol]):
                try:
                    val = float(v)
                except ValueError:
                    continue
                rows.append({"series": sid, "period": period_to_date(t), "value": val})
                n += 1
            note["observations"] = n
            notes[sid] = note
            if n == 0:
                errors.append(f"{sid}: response had no observations")
        except Exception as e:
            errors.append(f"{sid}: {type(e).__name__}: {e}")
    return rows, notes, errors
