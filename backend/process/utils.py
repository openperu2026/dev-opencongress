import re
import json
import polars as pl
from datetime import datetime
from sqlalchemy.orm import Session
from operator import attrgetter

from backend import PARTY_ALIASES, LegislativeYear
from backend.config import directories
from backend.database.raw_models import RawBill, RawMotion
from backend.process.schema import BillStep, MotionStep


def extract_text(text: str, initial: str = None, final: str = None) -> str:
    """
    Extracts the text between an specified initial and final texts. The initial
    or the final text could be optional, but not both

    Args:
        - text: original text
        - initial: initial part of the text to start
        - final: final part of the text to stop the extraction
    """
    assert initial or final, "Must specify either initial or final text"

    if initial and final:
        pattern = re.compile(f"{re.escape(initial)}(.*?){re.escape(final)}", re.DOTALL)
    elif initial and not final:
        pattern = re.compile(f"({re.escape(initial)})(.*)", re.DOTALL)
    else:
        pattern = re.compile(f"(.*?){re.escape(final)}", re.DOTALL)
    result = re.search(pattern, text)

    if not final:
        return result.group(2)
    else:
        return result.group(1)


def normalize_party_name(name: str) -> str:
    if name in PARTY_ALIASES.keys():
        canonical_name = PARTY_ALIASES[name]
        return canonical_name
    return name


def gen_congresistas_df(session: Session) -> None:
    """
    Extracts additional information from congresistas that are not in their
    profile page, but in the bills responses.

    Saves a JSON file at the processed directory.

    Args:
        session (Session): database Session
    """
    bills_congresistas = (
        session.query(RawBill.congresistas).filter(RawBill.last_update).distinct().all()
    )
    motions_congresistas = (
        session.query(RawMotion.congresistas)
        .filter(RawBill.last_update)
        .distinct()
        .all()
    )

    all_cong = []

    for (json_str,) in bills_congresistas + motions_congresistas:
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                all_cong.extend(parsed)
        except json.JSONDecodeError:
            continue

    unique_by_congresista = {
        d["congresistaId"]: d for d in all_cong if "congresistaId" in d
    }

    df = pl.DataFrame(list(unique_by_congresista.values()))

    df.write_json(directories.PROCESSED_DATA / "cong_info_2021_2026.json")

    return None


def get_current_leg_year(timestamp: str) -> LegislativeYear:
    """
    Maps a timestamp into a LegislativeYear
    """
    dt = datetime.fromisoformat(timestamp)
    year = dt.year

    # This cutoff relates to the Peruvian parliament dynamic: a legislative year
    # starts and ends on 28th of July of each year.
    cutoff = datetime(year, 7, 28)
    if dt < cutoff:
        # Before 28th July
        return LegislativeYear(str(year - 1))
    else:
        # After 28th July
        return LegislativeYear(str(year))


def create_vote_ids(
    step_list: list[BillStep | MotionStep],
) -> list[BillStep | MotionStep]:
    """
    Generate deterministic vote event IDs for a bill.

    Vote steps are first sorted by date. Each vote event is then assigned an ID
    using the format `<bill_id>_<n>`, where `n` represents the vote event's
    position in the sorted sequence.

    Args:
        step_list (list[BillStep | MotionStep]): Steps associated with a bill
        or motion.

    Returns:
        list[BillStep | MotionStep]: Sorted steps, with vote event IDs assigned
        to vote steps.
    """
    # Sorting steps based on step date
    sorted_list = sorted(step_list, key=attrgetter("step_date"))

    final_list = []
    vote_step_counter = 0
    for step in sorted_list:
        # In case is a vote_step, then it creates their vote_event_id
        if step.vote_step:
            vote_step_counter += 1
            if isinstance(step, BillStep):
                vote_id = f"{step.bill_id}_{vote_step_counter}"
            elif isinstance(step, MotionStep):
                vote_id = f"{step.motion_id}_{vote_step_counter}"
            step.vote_id = vote_id

        final_list.append(step)

    return final_list
