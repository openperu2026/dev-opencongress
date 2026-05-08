"""
Visual testing script for bill differences.

Processed DB mode (default) — reads from bill_differences table:
    python scripts/show_diff.py <bill_id> --list
    python scripts/show_diff.py <bill_id> --step <step_id>

Raw DB mode (--from-raw) — computes diffs live from raw documents,
no pipeline run needed, uses raw OCR text directly:
    python scripts/show_diff.py <bill_id> --from-raw --list
    python scripts/show_diff.py <bill_id> --from-raw --step <step_id>

Find bills with real text variance (good for visual testing):
    python scripts/show_diff.py --find-candidates

Options:
    --max-lines N     Max diff lines to show (default: 60)
    --snippet N       Chars of each version text to preview (default: 400)
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database.models import Base, Bill, BillDifference, BillStep, BillText
from backend.process.diff import compute_bill_difference

# ── ANSI ────────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
GREY = "\033[90m"
BOLD = "\033[1m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RESET = "\033[0m"
WIDTH = 88


def hr(char="─"):
    print(char * WIDTH)


def section(title):
    print(f"\n{BOLD}{CYAN}{title}{RESET}")
    hr()


def render_diff_lines(lines: list[str], max_lines: int) -> None:
    shown = 0
    for line in lines:
        if line.startswith("+ "):
            print(f"{GREEN}{line}{RESET}", end="")
        elif line.startswith("- "):
            print(f"{RED}{line}{RESET}", end="")
        elif line.startswith("? "):
            continue
        else:
            print(f"{GREY}{line}{RESET}", end="")
        shown += 1
        if shown >= max_lines:
            remaining = sum(1 for ln in lines[shown:] if not ln.startswith("? "))
            if remaining:
                print(
                    f"\n{YELLOW}  … {remaining} more lines hidden (use --max-lines N){RESET}"
                )
            return


def _text_snippet(t: str | None, n: int) -> str:
    if t is None:
        return f"{GREY}(none){RESET}"
    body = t[:n].replace("\n", "\n    ")
    suffix = f"{GREY}…{RESET}" if len(t) > n else ""
    return f"    {body}{suffix}"


# ── Processed DB mode ────────────────────────────────────────────────────────


def _ensure_schema(engine):
    with engine.connect() as conn:

        def _cols(table):
            return {
                r[1]
                for r in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            }

        bill_cols = _cols("bills")
        if "approved" not in bill_cols:
            conn.execute(
                text("ALTER TABLE bills ADD COLUMN approved BOOLEAN DEFAULT 0")
            )
            if "bill_approved" in bill_cols:
                conn.execute(text("UPDATE bills SET approved = bill_approved"))

        step_cols = _cols("bill_steps")
        if "vote_step" not in step_cols:
            conn.execute(
                text("ALTER TABLE bill_steps ADD COLUMN vote_step BOOLEAN DEFAULT 0")
            )
        if "vote_event_id" not in step_cols:
            conn.execute(text("ALTER TABLE bill_steps ADD COLUMN vote_event_id TEXT"))

        conn.commit()
    Base.metadata.create_all(engine)


def processed_list(db, bill):
    steps = (
        db.execute(
            select(BillStep)
            .where(BillStep.bill_id == bill.id)
            .order_by(BillStep.step_date.asc())
        )
        .scalars()
        .all()
    )

    if not steps:
        print(f"{YELLOW}No steps found.{RESET}")
        return

    section(f"Steps for {bill.id} ({len(steps)} total)")
    for step in steps:
        diff = db.get(BillDifference, step.id)
        dtype = diff.difference_type if diff else "no diff row"
        colour = {
            "modified": GREEN,
            "first_version": YELLOW,
            "no_change": GREY,
            "unavailable": RED,
            "incomparable": YELLOW,
        }.get(dtype, GREY)
        date_str = step.step_date.date() if step.step_date else "—"
        print(
            f"  {BOLD}{step.id:<10}{RESET} {date_str}  {step.step_type:<40} {colour}{dtype}{RESET}"
        )


def processed_step(db, bill, step_id: int, max_lines: int, snippet: int):
    step = db.get(BillStep, step_id)
    if not step or step.bill_id != bill.id:
        print(f"{RED}Step {step_id} not found for bill {bill.id}{RESET}")
        return

    diff = db.get(BillDifference, step_id)
    section(
        f"Step {step_id}  ·  {step.step_type}  ·  {step.step_date.date() if step.step_date else '—'}"
    )

    if not diff:
        print(
            f"{YELLOW}No BillDifference row — run the pipeline first (or use --from-raw).{RESET}"
        )
        return

    dtype = diff.difference_type
    label = {
        "first_version": f"{YELLOW}FIRST VERSION{RESET}",
        "no_change": f"{GREY}NO CHANGE{RESET}",
        "unavailable": f"{RED}UNAVAILABLE{RESET}",
        "modified": f"{GREEN}MODIFIED{RESET}",
    }.get(dtype, dtype)
    print(
        f"  type={label}  prev_step={diff.prev_step_id or '—'}  "
        f"new_archivo={diff.new_archivo_id or '—'}  old_archivo={diff.old_archivo_id or '—'}"
    )

    old_text = new_text = None
    if diff.old_archivo_id:
        bt = db.get(BillText, diff.old_archivo_id)
        old_text = bt.text if bt else None
    if diff.new_archivo_id:
        bt = db.get(BillText, diff.new_archivo_id)
        new_text = bt.text if bt else None

    print(
        f"\n  {BOLD}VERSION 1:{RESET} {'—' if old_text is None else f'{len(old_text)} chars'}"
    )
    print(_text_snippet(old_text, snippet))
    print(
        f"\n  {BOLD}VERSION 2:{RESET} {'—' if new_text is None else f'{len(new_text)} chars'}"
    )
    print(_text_snippet(new_text, snippet))

    if diff.difference_content:
        lines = json.loads(diff.difference_content)
        print(f"\n  {BOLD}DIFF ({len(lines)} lines):{RESET}")
        hr("·")
        render_diff_lines(lines, max_lines)
        hr("·")
    else:
        print(f"\n  {GREY}(no diff content — type is {dtype}){RESET}")


# ── Raw DB mode ──────────────────────────────────────────────────────────────


def _raw_docs_for_bill(raw_c, bill_id: str) -> list[dict]:
    rows = raw_c.execute(
        """
        SELECT seguimiento_id, archivo_id, step_date, LENGTH(text) as tlen, text
        FROM raw_bill_documents
        WHERE bill_id = ? AND text IS NOT NULL AND text != '' AND last_update = 1
        ORDER BY step_date ASC, archivo_id ASC
    """,
        (bill_id,),
    ).fetchall()
    return [
        {
            "step_id": r[0],
            "archivo_id": r[1],
            "step_date": r[2],
            "tlen": r[3],
            "text": r[4],
        }
        for r in rows
    ]


def raw_list(raw_c, bill_id: str):
    docs = _raw_docs_for_bill(raw_c, bill_id)
    if not docs:
        print(f"{YELLOW}No raw documents found for {bill_id}.{RESET}")
        return
    section(f"Raw documents for {bill_id} ({len(docs)} with text)")
    print(f"  {'step_id':<12} {'archivo_id':<12} {'date':<12} {'chars':>8}")
    hr("·")
    seen_steps = set()
    for d in docs:
        marker = "" if d["step_id"] not in seen_steps else f"{GREY}(dup step){RESET}"
        seen_steps.add(d["step_id"])
        print(
            f"  {str(d['step_id']):<12} {str(d['archivo_id']):<12} "
            f"{str(d['step_date']):<12} {d['tlen']:>8}  {marker}"
        )
    print(
        f"\n{GREY}  Tip: use --step <STEP_ID> to compare that step against the previous one.{RESET}"
    )


def raw_step(raw_c, bill_id: str, step_id: int, max_lines: int, snippet: int):
    docs = _raw_docs_for_bill(raw_c, bill_id)
    if not docs:
        print(f"{YELLOW}No raw documents for {bill_id}.{RESET}")
        return

    # Collect unique steps in order
    seen = {}
    for d in docs:
        sid = str(d["step_id"])
        if sid not in seen:
            seen[sid] = d

    step_ids_ordered = list(seen.keys())
    target = str(step_id)

    if target not in seen:
        print(f"{RED}Step {step_id} not found in raw documents for {bill_id}.{RESET}")
        print(f"  Available step_ids: {step_ids_ordered}")
        return

    idx = step_ids_ordered.index(target)
    new_doc = seen[target]
    old_doc = seen[step_ids_ordered[idx - 1]] if idx > 0 else None

    section(f"Step {step_id}  ·  date={new_doc['step_date']}  [RAW MODE]")

    result = compute_bill_difference(
        old_doc["text"] if old_doc else None,
        new_doc["text"],
    )
    dtype = result["type"]
    label = {
        "first_version": f"{YELLOW}FIRST VERSION{RESET}",
        "no_change": f"{GREY}NO CHANGE{RESET}",
        "unavailable": f"{RED}UNAVAILABLE{RESET}",
        "incomparable": f"{YELLOW}INCOMPARABLE (size ratio too large){RESET}",
        "modified": f"{GREEN}MODIFIED{RESET}",
    }.get(dtype, dtype)

    prev_info = (
        f"prev_step={old_doc['step_id']}  prev_archivo={old_doc['archivo_id']}"
        if old_doc
        else "prev=none (first)"
    )
    print(f"  type={label}  {prev_info}")
    print(f"  new_archivo={new_doc['archivo_id']}  new_chars={new_doc['tlen']}")
    if old_doc:
        print(f"  old_archivo={old_doc['archivo_id']}  old_chars={old_doc['tlen']}")

    old_chars = "—" if not old_doc else f"{old_doc['tlen']} chars"
    print(f"\n  {BOLD}VERSION 1 (raw):{RESET} {old_chars}")
    print(_text_snippet(old_doc["text"] if old_doc else None, snippet))
    print(f"\n  {BOLD}VERSION 2 (raw):{RESET} {new_doc['tlen']} chars")
    print(_text_snippet(new_doc["text"], snippet))

    if result["content"]:
        lines = result["content"]
        print(f"\n  {BOLD}DIFF ({len(lines)} lines):{RESET}")
        hr("·")
        render_diff_lines(lines, max_lines)
        hr("·")
    else:
        print(f"\n  {GREY}(no diff content — type is {dtype}){RESET}")


# ── Candidates finder ─────────────────────────────────────────────────────────


def find_candidates(raw_c, top: int = 15):
    rows = raw_c.execute("""
        SELECT bill_id, seguimiento_id, LENGTH(text) as tlen
        FROM raw_bill_documents
        WHERE text IS NOT NULL AND length(text) > 1000 AND last_update = 1
        ORDER BY bill_id, step_date ASC
    """).fetchall()

    by_bill = defaultdict(list)
    for bill_id, step, tlen in rows:
        by_bill[bill_id].append((step, tlen))

    candidates = []
    for bill_id, docs in by_bill.items():
        steps = {d[0] for d in docs}
        if len(steps) < 2:
            continue
        tlens = [d[1] for d in docs]
        variance = max(tlens) - min(tlens)
        candidates.append((bill_id, len(steps), len(docs), variance))

    candidates.sort(key=lambda x: -x[3])

    section(f"Top {top} bills with raw text variance across steps")
    print(f"  {'bill_id':<16} {'steps':>6} {'docs':>6} {'variance':>10}")
    hr("·")
    for bill_id, steps, docs, var in candidates[:top]:
        print(f"  {bill_id:<16} {steps:>6} {docs:>6} {var:>10,}")
    print(f"\n{GREY}  Run with --from-raw --list to inspect any of these.{RESET}")


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Visual testing for bill diffs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("bill_id", nargs="?", help="Bill ID (e.g. 2021_2907)")
    parser.add_argument("--step", type=int, metavar="STEP_ID")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Read from raw DB directly; no pipeline needed",
    )
    parser.add_argument(
        "--find-candidates",
        action="store_true",
        help="List bills with the most raw text variance (good test subjects)",
    )
    parser.add_argument("--max-lines", type=int, default=60, metavar="N")
    parser.add_argument(
        "--snippet",
        type=int,
        default=400,
        metavar="N",
        help="Chars of text to preview per version (default: 400)",
    )
    args = parser.parse_args()

    # ── candidates mode ──────────────────────────────────────────────────────
    if args.find_candidates:
        raw_c = sqlite3.connect(settings.RAW_DB_URL.replace("sqlite:///", ""))
        find_candidates(raw_c)
        print()
        return

    if not args.bill_id:
        parser.error("bill_id is required (or use --find-candidates)")

    # ── raw mode ─────────────────────────────────────────────────────────────
    if args.from_raw:
        raw_c = sqlite3.connect(settings.RAW_DB_URL.replace("sqlite:///", ""))

        # Still get bill title from processed DB if available
        engine = create_engine(settings.DB_URL)
        _ensure_schema(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            bill = db.get(Bill, args.bill_id)

        hr("═")
        if bill:
            print(f"{BOLD}BILL {bill.id}{RESET}  ·  {bill.title}")
            print(f"Status : {bill.status}  |  Period : {bill.leg_period}")
        else:
            print(
                f"{BOLD}BILL {args.bill_id}{RESET}  {YELLOW}(not in processed DB){RESET}"
            )
        print(f"{YELLOW}[raw mode — using raw OCR text directly]{RESET}")
        hr("═")

        if args.list or not args.step:
            raw_list(raw_c, args.bill_id)
            if not args.step:
                print()
                return
        if args.step:
            raw_step(raw_c, args.bill_id, args.step, args.max_lines, args.snippet)
        print()
        return

    # ── processed mode ───────────────────────────────────────────────────────
    engine = create_engine(settings.DB_URL)
    _ensure_schema(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        bill = db.get(Bill, args.bill_id)
        if not bill:
            print(
                f"{RED}Bill '{args.bill_id}' not found. Try --from-raw or --find-candidates.{RESET}"
            )
            sys.exit(1)

        hr("═")
        print(f"{BOLD}BILL {bill.id}{RESET}  ·  {bill.title}")
        print(f"Status : {bill.status}  |  Period : {bill.leg_period}")
        hr("═")

        if args.list or not args.step:
            processed_list(db, bill)
            if not args.step:
                print(
                    f"\n{GREY}Tip: --step <ID> to inspect a diff, --from-raw for live diffs.{RESET}\n"
                )
                return
        if args.step:
            processed_step(db, bill, args.step, args.max_lines, args.snippet)

    print()


if __name__ == "__main__":
    main()
