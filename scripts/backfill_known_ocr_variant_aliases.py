"""
Backfill aliases for specific OCR-garbled name variants observed in
production `make process-votes-from-raw` runs on 2026-08-18.

Unlike scripts/backfill_surname_aliases.py (which derives a rule --
"unambiguous surname" -- and applies it to all 140 congresistas), this is
a hand-curated, manually-verified list. Some of these names are hard
enough to OCR that the same real person shows up misspelled a different
way in nearly every document (e.g. 9 distinct variants of "Nivardo Edgar
Tello Montes"' given name alone). A naive best-fuzzy-match search gets
several of these WRONG (e.g. it picks an unrelated person for some of the
"Jáuregui Martínez de Aguayo" variants because raw Jaro-Winkler score
doesn't know that a long, rare, exact-matching surname is much stronger
evidence than a marginally higher score from an unrelated name) -- so
this list was built by manual review, not by trusting the top suggestion.

Explicitly excluded (too risky to alias -- see the design conversation
this script came out of):
  - Names where the suggested match's surname doesn't actually match
    (e.g. 'ALEJANDRO QUIROZ BARBOZA', 'HERNANDO RAMÍREZ GARCÍA').
  - 'PAUL SILVIO QUITO SARMIENTO' / 'WILSON RUSSELL QUITO SARMIENTO' --
    look like a given name from one roster row merged with a DIFFERENT
    real person's surname (Bernardo Jaime Quito Sarmiento exists
    separately) -- aliasing either risks misattributing a real vote.
  - 'PERÚ LIBRE' -- a political party name extracted into the full_name
    field by mistake, not a person at all.
  - A handful of very low fuzzy-score names with no confident mapping
    ('MONTEFARI', 'MONTOYA CUBAS', 'MONTOYA FIGARI', 'PICÓN QUELDO').
These stay unresolved; review_app is the right tool for them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.database import models as db_models
from backend.database.crud.pipeline_core import save_alias

# target full_name (must match Congresista.full_name exactly) -> observed
# garbled variants to alias to that person.
ALIAS_MAP: dict[str, list[str]] = {
    "Alejandro Aurelio Aguinaga Recuenco": [
        "ALEJANDRO AGUINAGA RECAVARREN",
        "ALEJANDRO AGUINAGA RECUNCO",
    ],
    "Auristela Ana Obando Morgan": [
        "AURI STELE OBANDO MORGAN",
        "ARLETT ANA OBANDO MORGAN",
        "ARLETTANA ANA OBANDO MORGAN",
    ],
    "Carlos Javier Zeballos Madariaga": [
        "CARLOS ZEBALLOS MADIARIAGA",
        "CARLOS ZEBALLOS MADIARAGA",
        "CARLOS ZEBALLOS MADIARRAGA",
        "CARLOS ZEBALLOS MARDIAGA",
        "CARLOS ZEVALLOS MADARIAGA",
    ],
    "Víctor Raúl Cutipa Ccama": ["CUITIPA CCAMA"],
    "Hamlet Echeverría Rodríguez": ["ECHEVARRÍA RODRÍGUEZ"],
    "Nivardo Edgar Tello Montes": [
        "EDWARD EDGAR TELLO MONTES",
        "EDWARD TELLO MONTES",
        "NARVARD EDGAR TELLO MONTES",
        "NARVARDO EDGAR TELLO MONTES",
        "NIDIA EDGAR TELLO MONTES",
        "NITARDO EDGAR TELLO MONTES",
        "NYARV EDGAR TELLO MONTES",
        "NYRVANA EDGAR TELLO MONTES",
        "NYRVAR EDGAR TELLO MONTES",
        "RICARDO EDGAR TELLO MONTES",
    ],
    "Gladys Margot Echaíz de Núñez Izaga": [
        "GLADYS M. ECHAEZ DE NÚÑEZ IZAGA",
        "GLADYS M. ECHAFIZ DE NÚÑEZ IZAGA",
        "GLADYS M. ECHAFÍZ DE NÚÑEZ IZAGA",
        "GLADYS M. ECHAZ DE NÚÑEZ IZAGA",
        "GLADYS M. ECHAZE DE NÚÑEZ IZAGA",
        "GLADYS M. ECHAZÚ DE NÚÑEZ IZAGA",
        "GLADYS M. ECHZATE DE NÚÑEZ IZAGA",
        # Round 3 (2026-08-19): a completely different name STRUCTURE than
        # the variants above (those garbled "Echaíz de Núñez Izaga") --
        # this batch of source documents apparently prints her fuller
        # legal name, including "Vda de" (widow of) and an extra surname
        # "Ramos" that Congresista.full_name doesn't capture. Verified
        # unambiguous: she's the only "Gladys" in the 140-person roster,
        # and the surname already partially overlaps ("Echaíz", "Núñez").
        "GLADYS ECHAIZ RAMOS VDA DE NUÑEZ",
        "GLADYS ECHAIZ RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHAIZ RAMOS VDA. DE NÚÑEZ",
        "GLADYS ECHAIZ RAMOS VOA DE NÚÑEZ",
        "GLADYS ECHAÍZ RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHATZ RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHAZ RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHAZI RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHAZÚ RAMOS VDA DE NÚÑEZ",
        "GLADYS ECHAZÚ RAMOS VDA. DE NÚÑEZ",
        "GLADYS ECHAÍZ RAMOS VDA DE NUÑEZ",
        "GLADYS ECHAÍZ RAMOS VDA. DE NÚÑEZ",
        "GLADYS ECHÁIZ RAMOS VDA DE NÚÑEZ",
    ],
    "Jorge Samuel Coayla Juárez": ["GORGIO SAMUEL COAYLA JUÁREZ"],
    "Heidy Lisbeth Juárez Calle": ["HEDY LIZBETH JUÁREZ CALLE"],
    "Idelso Manuel García Correa": [
        "ID ELISO MANUEL GARCÍA CORREA",
        "IDLERSO MANUEL GARCÍA CORREA",
    ],
    "Hilda Marleny Portero López": ["IDA MARLENY PORTERO LÓPEZ"],
    "María Jessica Córdova Lobatón": ["JANET JESSICA CÓRDOVA LOBATÓN"],
    "Juan Carlos Martin Lizarzaburu Lizarzaburu": [
        "JUAN C. LIZARRABURU LIZARRABURU",
        "JUAN C. LIZÁRRABURU LIZARRABURU",
        "JUAN C. LIZÁRRABURU LIZÁRRABURU",
        "JUAN C. LIZARRABURU LIZARZABURU",
        "JUAN C. LIZÁRRABURU LIZARZABURU",
        "JUAN C. LIZÁRRAGA LIZÁRRABURU",
        "JUAN C. LIZÁRRAGA LIZÁRRAGA",
        "JUAN C. LIZÁRRUBURU LIZÁRRUBURU",
    ],
    "José Alberto Arriola Tueros": ["LUIS ALBERTO ARRIOLA TUEROS"],
    "Nieves Esmeralda Limachi Quispe": ["LUIS NESMARALDA LIMACHI QUISPE"],
    "María de los Milagros Jackeline Jáuregui Martínez de Aguayo": [
        "MARÍA DEL CARMEN JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA J. JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA JAUREGUI CASTAÑEDA DE AGUAYO",
        "MARÍA JÁUREGUI ESTRADA DE AGUAYO",
        "MARÍA JAÚREGUI MENDOZA DE AGUAYO",
        "MARÍA JÁUREGUI MENDOZA DE AGUAYO",
        "MARÍA JÁUREGUI MURTNEZ DE AGUAYO",
        "MARÍA JÁUREGUI RETEGUI DE AGUAYO",
        "MARÍA JENNY JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA MARGARITA JÁUREGUI DE AGUAYO",
        "MARÍA MARGARITA JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA SOLEDAD JÁUREGUI MARTÍNEZ DE AGUAYO",
        "MARÍA LE JÁUREGUI MARTÍNEZ DE AGUAYO",
    ],
    "María del Carmen Alva Prieto": ["MARÍA MARGARITA ALVA PRIETO"],
    "Mery Eliana Infantes Castañeda": ["MERLY JULIANA INFANTES CASTAÑEDA"],
    "Raúl Huamán Coronado": [
        "RODRIGO HUAMÁN CORONADO",
        "ROLANDO HUAMÁN CORONADO",
        "RUTH HUAMÁN CORONADO",
    ],
    "Hitler Saavedra Casternoque": [
        "SAAVEDRA CASTERN0QUE",
        "SAAVEDRA CASTERNOUQE",
        "SAAVEDRA CASTERNOUQUE",
    ],
    "Susel Ana María Paredes Piqué": [
        "SUSAN ELEN ASMARÍA PAREDES PIQUÉ",
        "SUSAN ELENA MARÍA PAREDES PIQUÉ",
        "SUSAN ELIZABETH PAREDES PIQUÉ",
    ],
    "Tania Estefany Ramírez García": [
        "TANIA ESTEFANY RAMÍREZ GARCÍA",  # Cyrillic А homoglyph normalized here
        "TATIANA ESTEFANY RAMÍREZ GARCÍA",
    ],
    "Nilza Merly Chacón Trujillo": ["NILZA MERLY CHUQUILLANQUI TRUJILLO"],
    "Noelia Rossvith Herrera Medina": [
        "NELIDA ROSSVITH GUERRERO MEDINA",
        "NIDIA ROSSVITH HERRERA MEDINA",
        "NORMA ROSSYTH HERRERA MEDINA",
    ],
    "Jorge Arturo Zeballos Aponte": ["JORGE ZEBALLOS OPORTO", "JORGE ZEBAILLOS APONTE"],
    # --- round 3, added 2026-08-19 after a $10-budget-capped extraction run ---
    "Fernando Miguel Rospigliosi Capurro": [
        # Same words as the canonical name, just reordered (surname-first,
        # no comma this time) -- a word-order variant without the comma
        # delimiter my pipeline_core.py fix keys off of.
        "ROSIGLIOSI CAPURRO FERNANDO MIGUEL",
        "ROSPLIGLIOSI CAPURRO FERNANDO MIGUEL",
    ],
    "Javier Rommel Padilla Romero": ["JAVIER PADILLA ROMMEL"],
    "Yorel Kira Alcarraz Agüero": ["YOEL KIRA ALCARraz AGÜERO"],
    "María Grimaneza Acuña Peralta": [
        # "Acuña Peralta" alone is one of the 2 ambiguous surnames skipped
        # by backfill_surname_aliases.py -- but these two variants include
        # the given name ("María G[rimaneza]"), which disambiguates from
        # the other Acuña Peralta (Segundo Héctor), so they're safe here.
        "MARÍA G. ACUÑA PERALTA",
        "MARÍA G림enaZ ACUÑA PERALTA",
    ],
}


def main() -> int:
    engine = create_engine(settings.DB_URL)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        created = 0
        skipped_existing = 0
        not_found = 0

        for target_full_name, variants in ALIAS_MAP.items():
            cong = db.scalar(
                select(db_models.Congresista).where(
                    db_models.Congresista.full_name == target_full_name
                )
            )
            if cong is None:
                logger.error(
                    f"No Congresista found with full_name={target_full_name!r}"
                )
                not_found += len(variants)
                continue

            for variant in variants:
                if save_alias(db, cong, variant):
                    created += 1
                else:
                    skipped_existing += 1

        db.commit()
        logger.info(
            f"Done. created={created} skipped_existing={skipped_existing} "
            f"not_found={not_found}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
