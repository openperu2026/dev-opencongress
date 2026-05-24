from __future__ import annotations

import json
from collections import Counter, defaultdict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.database import models
from backend.database.crud.pipeline_core import find_congresista

# --- Conversion maps ---

VOTE_MAP = {
    "SI": "Sí",
    "NO": "No",
    "ABST": "Abstención",
    "ABST.": "Abstención",
    "SINRES": "Sin respuesta",
    "AUS": "Sin respuesta",
    "LO": "Sin respuesta",
    "LE": "Sin respuesta",
    "LP": "Sin respuesta",
}

ATTENDANCE_MAP = {
    "PRE": "Presente",
    "AUS": "Ausente",
    "LO": "Con licencia",
    "LE": "Con licencia",
    "LP": "Con licencia",
    "COM": "Con licencia",
    "CEI": "Con licencia",
    "JP": "Con licencia",
    "BAN": "Con licencia",
    "SUS": "Suspendido",
    "F": "Suspendido",
}

# temporary until Organization gains a short_name column
BANCADA_ABBR = {
    "FP": "Fuerza Popular",
    "APP": "Alianza Para El Progreso",
    "PP": "Podemos Perú",
    "PL": "Perú Libre",
    "RP": "Renovación Popular",
    "JPP-VP": "Juntos por el Perú – Voces del Pueblo",
    "SP": "Somos Perú",
    "AP": "Acción Popular",
    "AP-PIS": "Avanza País – Partido de Integración Social",
    "BS": "Bancada Socialista",
    "HYD": "Honor y Democracia",
    "BDP": "Bloque Democrático Popular",
    "NA": "No Agrupados",
}


def normalize_name(name: str) -> str:
    if "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip()}"
    return name.strip().lower()


def convert_vote(raw: str) -> str | None:
    return VOTE_MAP.get(raw.strip().upper())


def convert_attendance(raw: str) -> str | None:
    return ATTENDANCE_MAP.get(raw.strip().upper())


def _find_congresista(
    db: Session,
    name: str,
    _cache: dict[str, models.Congresista | None] = {},
) -> models.Congresista | None:
    key = normalize_name(name)
    if key not in _cache:
        _cache[key] = find_congresista(db, key)
    return _cache[key]


def ingest_vote_events(db: Session, results) -> None:
    bancada_by_name = {
        org.org_name: org
        for org in db.query(models.Organization)
        .filter(models.Organization.org_type == "Bancada")
        .all()
    }
    bancada_by_abbr = {
        abbr: bancada_by_name.get(full_name) for abbr, full_name in BANCADA_ABBR.items()
    }

    grouped = defaultdict(lambda: {"meta": None, "pages": []})
    for raw_page, step_date, bill_id, vote_event_id, org_id in results:
        grouped[vote_event_id]["meta"] = (step_date, bill_id, org_id)
        grouped[vote_event_id]["pages"].append(json.loads(raw_page.text))

    for vote_event_id, info in grouped.items():
        step_date, bill_id, org_id = info["meta"]
        pages = {data[0]["page_type"]: data for data in info["pages"] if data}

        if "voting" in pages:
            vote_rows = []
            counts: Counter = Counter()

            for row in pages["voting"]:
                congresista = _find_congresista(db, row["name"])
                bancada = bancada_by_abbr.get(row["party"])
                if congresista and bancada:
                    option = convert_vote(row["value"])
                    if option is None:
                        continue
                    vote_rows.append((congresista, bancada, option))
                    if option in ("Sí", "No", "Abstención"):
                        counts[(option, bancada.org_id)] += 1

            total_yes = sum(v for (opt, _), v in counts.items() if opt == "Sí")
            total_no = sum(v for (opt, _), v in counts.items() if opt == "No")
            total_abstain = sum(
                v for (opt, _), v in counts.items() if opt == "Abstención"
            )
            result = "Aprobado" if total_yes > total_no else "Rechazado"

            stmt = (
                insert(models.VoteEvent)
                .values(
                    vote_event_id=vote_event_id,
                    org_id=org_id,
                    bill_id=bill_id,
                    motion_id=None,
                    event_date=step_date,
                    result=result,
                    votes_in_favor=total_yes,
                    votes_against=total_no,
                    votes_abstention=total_abstain,
                )
                .on_conflict_do_nothing()
            )
            db.execute(stmt)
            db.flush()

            vote_event_created = db.get(models.VoteEvent, vote_event_id) is not None

            if vote_event_created:
                for congresista, bancada, option in vote_rows:
                    stmt = (
                        insert(models.Vote)
                        .values(
                            vote_event_id=vote_event_id,
                            voter_id=congresista.id,
                            option=option,
                            bancada_id=bancada.org_id,
                        )
                        .on_conflict_do_nothing()
                    )
                    db.execute(stmt)

                for (option, bancada_id), count in counts.items():
                    stmt = (
                        insert(models.VoteCounts)
                        .values(
                            vote_event_id=vote_event_id,
                            option=option,
                            bancada_id=bancada_id,
                            count=count,
                        )
                        .on_conflict_do_nothing()
                    )
                    db.execute(stmt)

        if "attendance" in pages and vote_event_created:
            for row in pages["attendance"]:
                congresista = _find_congresista(db, row["name"])
                if congresista:
                    stmt = (
                        insert(models.Attendance)
                        .values(
                            event_id=vote_event_id,
                            attendee_id=congresista.id,
                            status=convert_attendance(row["value"]),
                        )
                        .on_conflict_do_nothing()
                    )
                    db.execute(stmt)
