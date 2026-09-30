"""Offline test: fake the three sources, run collect twice, then build the dashboard.

    python tests/test_pipeline.py [--keep DIR]

Fixtures imitate each source's published layout (RBA CSV metadata rows, Valuer-General
workbooks with a title row and quarter headers, ABS SDMX CSV with labels). All numbers
here are synthetic test values, not market data.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import openpyxl
import pandas as pd
import xlwt

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build_dashboard  # noqa: E402
import collect  # noqa: E402
from watch import abs_sdmx, common, rba, vgv  # noqa: E402

SUBURBS = ["HIGHETT", "HAMPTON EAST", "CHELTENHAM", "MOORABBIN"]
OTHERS = ["HAMPTON", "BRIGHTON EAST", "MENTONE"]


def rba_csv(title: str, cols: list[tuple[str, str, str]], months: list[str], values) -> bytes:
    """cols: (title, type, series id)."""
    rows = [[f"{title}"], ["Title"] + [c[0] for c in cols], ["Description"] + [c[0] for c in cols],
            ["Frequency"] + ["Monthly"] * len(cols), ["Type"] + [c[1] for c in cols],
            ["Units"] + ["Per cent"] * len(cols), [], [], ["Source"] + ["RBA"] * len(cols),
            ["Publication date"] + ["01-Sep-2026"] * len(cols), ["Series ID"] + [c[2] for c in cols]]
    for i, m in enumerate(months):
        rows.append([m] + [f"{values(j, i):.2f}" for j in range(len(cols))])
    out = io.StringIO()
    for r in rows:
        out.write(",".join(r) + "\n")
    return out.getvalue().encode("cp1252")


def quarterly_xls(quarters: list[str], bump: float) -> bytes:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Median House")
    ws.write(0, 0, "Victorian Property Sales Report – Median House by Suburb")
    head = ["Locality"] + quarters + [f"No. of Sales {quarters[-1]}", "Change (%) quarter", "Change (%) year"]
    for j, v in enumerate(head):
        ws.write(2, j, v)
    for i, name in enumerate(SUBURBS + OTHERS):
        ws.write(3 + i, 0, name)
        for j, _ in enumerate(quarters):
            ws.write(3 + i, 1 + j, 1_000_000 + i * 90_000 + j * 12_000 + (bump if j == len(quarters) - 1 else 0))
        ws.write(3 + i, 1 + len(quarters), 20 + i)
        ws.write(3 + i, 2 + len(quarters), "1.2")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def annual_xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Median house prices by suburb 2015–2025"])
    ws.append([])
    ws.append(["Locality"] + list(range(2015, 2026)) + ["Change 2024-2025 (%)", "Growth pa 2015-2025 (%)"])
    for i, name in enumerate(SUBURBS + OTHERS):
        ws.append([name.title()] + [700_000 + i * 60_000 + k * 45_000 for k in range(11)] + [3.1, 4.2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def abs_csv(months: list[str]) -> bytes:
    df = pd.DataFrame({
        "DATAFLOW": "ABS:LF(1.0.0)", "MEASURE: Measure": "M13: Unemployment rate", "SEX: Sex": "3: Persons",
        "AGE: Age": "1599: Total (age)", "TSEST: Adjustment Type": "20: Seasonally Adjusted",
        "REGION: Region": "2: Victoria", "FREQ: Frequency": "M: Monthly",
        "TIME_PERIOD: Time Period": months, "OBS_VALUE": [4.1 + 0.02 * i for i in range(len(months))]})
    return df.to_csv(index=False).encode()


class FakeResp:
    def __init__(self, content: bytes, url: str, status: int = 200):
        self.content, self.url, self.status_code = content, url, status
        self.text = content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


class FakeSession:
    def __init__(self, routes):
        self.routes = routes

    def get(self, url, **kw):
        for key, content in self.routes.items():
            if key in url:
                return FakeResp(content, url)
        return FakeResp(b"not found", url, 404)


def routes(stage: int):
    months = ["31-Jan-2026", "28-Feb-2026", "31-Mar-2026", "30-Apr-2026", "31-May-2026", "30-Jun-2026",
              "31-Jul-2026", "31-Aug-2026"] + (["30-Sep-2026"] if stage == 2 else [])
    early = [f"{d}-{m}-{y}" for y in (2024, 2025) for d, m in (("31", "Jan"), ("30", "Jun"), ("31", "Dec"))]
    months = early + months
    wave = lambda j, i: 3.0 + j * 0.8 + (0.25 if i < 7 else 0)  # noqa: E731
    qs = ["Mar 2025", "Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026"] + (["Jun 2026"] if stage == 2 else [])
    page = ('<html><body><a href="/__data/assets/excel_doc/0037/1/median-house-march-quarter-2026.xls">'
            'Median house – March quarter 2026 xls 255.0 KB</a> <a href="/__data/assets/excel_doc/0033/2/'
            'houses-by-suburb-2015-2025.xlsx">Houses by suburb 2015-2025 xlsx 134.7 KB</a>'
            '<a href="/x/median-unit-march-quarter-2026.xls">Median unit – March quarter 2026</a></body></html>')
    return {
        "property-sales-statistics": page.encode(),
        "median-house-march-quarter-2026.xls": quarterly_xls(qs, 25_000 if stage == 2 else 0),
        "houses-by-suburb-2015-2025.xlsx": annual_xlsx(),
        "f1.1-data.csv": rba_csv("F1.1 INTEREST RATES", [("Cash Rate Target", "Original", "FIRMMCRTD"),
                                                         ("Interbank Overnight Cash Rate", "Original", "FIRMMCRI")], months, wave),
        "f6-data.csv": rba_csv("F6 HOUSING LENDING RATES", [
            ("Lending rates; Housing loans; Investor; Variable; New loans funded", "Original", "FLRHIVN"),
            ("Lending rates; Housing loans; Owner-occupier; Variable; New loans funded in the month", "Original", "FLRHOVN"),
            ("Lending rates; Housing loans; Owner-occupier; Variable; Outstanding", "Original", "FLRHOVO")], months,
            lambda j, i: 5.6 + j * 0.3 - (0.25 if i >= 7 else 0)),
        "g1-data.csv": rba_csv("G1 CONSUMER PRICE INFLATION", [("Consumer price index; All groups", "Original", "GCPIAG"),
                                                               ("Year-ended inflation", "Original", "GCPIAGYP"),
                                                               ("Year-ended trimmed mean inflation", "Seasonally adjusted", "GCPIOCPMTMYP")],
                               months, lambda j, i: [140.0 + i, 3.4 - i * 0.05, 3.0][j]),
        "h5-data.csv": rba_csv("H5 LABOUR FORCE", [("Unemployment rate", "Seasonally adjusted", "GLFSURSA")], months,
                               lambda j, i: 4.0 + i * 0.03),
        "d1-data.csv": rba_csv("D1 GROWTH IN FINANCIAL AGGREGATES", [
            ("Credit; Housing; Monthly growth", "Seasonally adjusted", "DGFACHM"),
            ("Credit; Owner-occupier housing; Twelve-month-ended growth", "Seasonally adjusted", "DGFACOHNF"),
            ("Credit; Housing; Twelve-month-ended growth", "Seasonally adjusted", "DGFACH12")], months,
            lambda j, i: [0.5, 5.0, 5.5 + i * 0.02][j]),
        "data.api.abs.gov.au": abs_csv(["2026-06", "2026-07", "2026-08"] + (["2026-09"] if stage == 2 else [])),
    }


def run(stage: int, tmp: Path):
    fake = FakeSession(routes(stage))
    for mod in (rba, vgv, abs_sdmx):
        mod.session = lambda: fake
    common.DATA, common.CHANGES = tmp / "data", tmp / "data" / "changes.csv"
    collect.ROOT = tmp
    shutil.copy(ROOT / "config.yaml", tmp / "config.yaml")
    collect.main()


def check_layouts():
    """Other workbook layouts the Valuer-General has used or might use."""
    names = ["Highett", "Hampton East", "Cheltenham", "Moorabbin"]
    body = [[n.upper(), "$1,100,000", 1_120_000, "NA", 1_150_000, "1,160,000"] for n in SUBURBS]
    two_row = pd.DataFrame([["Median house price by suburb"], [None, "Jan - Mar", "Apr - Jun", "Jul - Sep", "Oct - Dec", "Jan - Mar"],
                            ["Suburb", 2025, 2025, 2025, 2025, 2026]] + body)
    rows, missing, _ = vgv.extract({"s": two_row}, names)
    assert not missing and {r["period"] for r in rows} == {"2025-Q1", "2025-Q2", "2025-Q4", "2026-Q1"}, rows
    assert next(r for r in rows if r["period"] == "2025-Q1")["median_price"] == 1_100_000

    blocks = pd.DataFrame([["Victorian Property Sales Report"], [None, "Median ($)", None, None, "No. of sales", None, None],
                           ["Locality", "Jul - Sep 2025", "Oct - Dec 2025", "Jan - Mar 2026", "Jul - Sep 2025", "Oct - Dec 2025", "Jan - Mar 2026"]]
                          + [[n, 1_300_000, 1_310_000, 1_320_000, 31, 28, 35] for n in SUBURBS])
    rows, missing, _ = vgv.extract({"s": blocks}, names)
    got = {(r["suburb"], r["period"]): (r["median_price"], r["sales_count"]) for r in rows}
    assert not missing and got[("Highett", "2026-Q1")] == (1_320_000, 35) and len(rows) == 12, got

    for text, want in [("Mar qtr 2026", ("Q", "2026-Q1")), ("Oct-Dec 2025", ("Q", "2025-Q4")), ("Sep-25", ("Q", "2025-Q3")),
                       ("2024", ("A", "2024")), (2019, ("A", "2019")), ("Change (%) Mar 2025 - Mar 2026", None),
                       ("No. of Sales Nov 2025", None), ("2025 (prelim)", ("A", "2025"))]:
        assert vgv.parse_period(text) == want, (text, vgv.parse_period(text))


def main():
    check_layouts()
    keep = Path(sys.argv[sys.argv.index("--keep") + 1]) if "--keep" in sys.argv else None
    tmp = Path(tempfile.mkdtemp())
    run(1, tmp)
    diag = json.loads((tmp / "data" / "_diagnostics.json").read_text())
    assert all(diag[k]["status"] == "ok" for k in ("vgv", "rba", "abs")), diag
    assert diag["rba"]["notes"]["mortgage_rate"]["series_id"] == "FLRHOVN", diag["rba"]["notes"]["mortgage_rate"]
    assert diag["rba"]["notes"]["inflation"]["series_id"] == "GCPIAGYP"
    assert diag["rba"]["notes"]["housing_credit"]["series_id"] == "DGFACH12"
    sm = pd.read_csv(tmp / "data" / "sales_medians.csv")
    assert set(sm.suburb) == {"Highett", "Hampton East", "Cheltenham", "Moorabbin"}, set(sm.suburb)
    assert len(sm[sm.freq == "Q"]) == 20 and len(sm[sm.freq == "A"]) == 44, sm.freq.value_counts()
    q1 = sm[(sm.suburb == "Highett") & (sm.period == "2026-Q1")].iloc[0]
    assert q1.median_price == 1_048_000 and q1.sales_count == 20, q1
    log = pd.read_csv(tmp / "data" / "changes.csv")
    assert list(log.kind) == ["baseline", "baseline"], log

    run(2, tmp)  # new quarter, revised Mar qtr, new month everywhere
    log = pd.read_csv(tmp / "data" / "changes.csv", keep_default_na=False)
    fresh = log[log.kind != "baseline"]
    assert len(fresh[(fresh.dataset == "sales_medians") & (fresh.kind == "new")]) == 4, fresh
    assert len(fresh[(fresh.dataset == "sales_medians") & (fresh.kind == "revised")]) == 0
    assert len(fresh[(fresh.dataset == "macro") & (fresh.kind == "new")]) == 6, fresh
    again = pd.read_csv(tmp / "data" / "sales_medians.csv")
    assert len(again[again.freq == "Q"]) == 24  # history kept, new quarter added

    out = keep or tmp
    data = build_dashboard.build(tmp / "data", out)
    assert len(data["changes"]) >= 3 and data["status"][0]["status"] == "ok"
    html = (out / "docs" / "index.html").read_text()
    assert html.startswith("<!doctype html>") and "__DATA__" not in html
    frag = (out / "dashboard" / "artifact.html").read_text()
    assert frag.startswith("<title>") and "<body" not in frag
    if keep:
        shutil.copytree(tmp / "data", keep / "data", dirs_exist_ok=True)
    print("All pipeline checks passed.", f"Output in {out}")


if __name__ == "__main__":
    main()
