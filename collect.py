"""Run every collector once. Safe to run as often as you like: unchanged data writes nothing new.

Exit code is always 0 so partial results still get committed; sources that failed are
listed in .watch_failed, which the workflow checks last (a failed run emails you).
"""
from __future__ import annotations

import yaml

from watch import abs_sdmx, rba, vgv
from watch.common import ROOT, upsert, write_diagnostics


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    src = cfg["sources"]
    suburbs = [s["name"] for s in cfg["suburbs"]]
    diag, failed = {}, []

    try:
        rows, notes = vgv.collect(src["vgv"], suburbs)
        counts = upsert("sales_medians", rows, ["suburb", "freq", "period"],
                        ["median_price", "sales_count"], "suburb")
        status = "ok" if not notes["missing"] else "partial"
        diag["vgv"] = {"status": status, "counts": counts, "notes": notes}
        if status != "ok":
            failed.append("vgv")
    except Exception as e:
        diag["vgv"] = {"status": "error", "message": f"{type(e).__name__}: {e}"}
        failed.append("vgv")

    macro_rows = []
    for name, mod in (("rba", rba), ("abs", abs_sdmx)):
        if name not in src:
            continue
        try:
            rows, notes, errors = mod.collect(src[name])
            macro_rows += rows
            status = "ok" if not errors else ("partial" if rows else "error")
            diag[name] = {"status": status, "notes": notes, "message": "; ".join(errors)}
            if errors:
                failed.append(name)
        except Exception as e:
            diag[name] = {"status": "error", "message": f"{type(e).__name__}: {e}"}
            failed.append(name)
    if macro_rows:
        diag["macro_store"] = {"status": "ok",
                               "counts": upsert("macro", macro_rows, ["series", "period"], ["value"], "series")}

    write_diagnostics(diag)
    (ROOT / ".watch_failed").write_text("\n".join(failed))


if __name__ == "__main__":
    main()
