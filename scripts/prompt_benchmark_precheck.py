"""
Step 0 pre-check for the prompt-strategy benchmark (see
docs/designs/vote-extraction-prompt-benchmark.md).

Measures, against every already-loaded extraction record, what fraction of
roster/roll `full_name` occurrences fail to resolve via `find_congresista` --
the exact production name-matching path used by `load.py`. Read-only: no
writes anywhere.

Also writes the list of failing (unresolved) distinct name spellings to
--fails-out, so they can be manually classified (resolver-fixable-
punctuation / genuinely-not-in-roster / real-OCR-error) before deciding
whether scripts/prompt_benchmark.py's full-roster arm is worth building.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database.crud.pipeline_core import find_congresista
from backend.database.raw_models import RawBillPage, RawMotionPage


def collect_name_occurrences(db, model) -> list[str]:
    """Every attendance[].roster[].full_name and votings[].roll[].full_name
    string from every page_num=0, processed, match_found=True record."""
    rows = db.scalars(
        select(model).where(model.page_num == 0, model.processed.is_(True))
    ).all()

    occurrences: list[str] = []
    for row in rows:
        try:
            record = json.loads(row.text)
        except (ValueError, TypeError):
            continue
        parsed = record.get("parsed") if isinstance(record, dict) else None
        if not parsed or not parsed.get("match_found"):
            continue
        for attendance in parsed.get("attendance") or []:
            for entry in attendance.get("roster") or []:
                full_name = entry.get("full_name")
                if full_name:
                    occurrences.append(full_name)
        for voting in parsed.get("votings") or []:
            for entry in voting.get("roll") or []:
                full_name = entry.get("full_name")
                if full_name:
                    occurrences.append(full_name)
    return occurrences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fails-out",
        type=Path,
        default=Path("var/prompt_benchmark_precheck_fails.json"),
        help="Where to write the list of failing distinct name spellings.",
    )
    args = parser.parse_args()
    args.fails_out.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)
    db = Session()

    bill_occurrences = collect_name_occurrences(db, RawBillPage)
    motion_occurrences = collect_name_occurrences(db, RawMotionPage)
    all_occurrences = bill_occurrences + motion_occurrences

    unique_names = sorted(set(all_occurrences))
    print(
        f"Loaded records: bills+motions -> "
        f"{len(bill_occurrences) + len(motion_occurrences)} name occurrences, "
        f"{len(unique_names)} distinct spellings"
    )

    t0 = time.time()
    fails: list[str] = []
    for i, name in enumerate(unique_names):
        cong = find_congresista(db, name=name)
        if cong is None:
            fails.append(name)
        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            print(f"  matched {i + 1}/{len(unique_names)} ({elapsed:.0f}s elapsed)")

    fails_set = set(fails)
    failed_occurrences = sum(1 for n in all_occurrences if n in fails_set)

    unique_rate = len(fails) / len(unique_names) if unique_names else 0.0
    occurrence_rate = (
        failed_occurrences / len(all_occurrences) if all_occurrences else 0.0
    )

    print(
        f"\nUnique-spelling failure rate: {len(fails)}/{len(unique_names)} "
        f"= {unique_rate:.1%}"
    )
    print(
        f"Occurrence-weighted failure rate: {failed_occurrences}/"
        f"{len(all_occurrences)} = {occurrence_rate:.2%}"
    )

    args.fails_out.write_text(
        json.dumps(sorted(fails), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nFailing distinct names written to {args.fails_out}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
