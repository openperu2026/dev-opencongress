# Data Model

This document describes the data entities, relationships, and storage layers in OpenCongress/Congreso Abierto. It serves as a reference for contributors working with the database models, processing pipelines, or API layer.

## Overview

Congreso Abierto maintains two separate database layers:

- **Raw layer**: stores data as close to the source as possible. Each record maps to a scraped page, downloaded PDF, or extracted text from an specific page. Raw data is append-only and never modified after ingestion, which make it possible to keep track to changes in contents.
- **Processed layer**: stores cleaned, validated, and normalized entities ready for analysis and frontend consumption. This is the layer the frontend and future enhancements will query.

Both layers are stored in PostgreSQL and are modeled with SQLAlchemy ORM (the processed layer additionally uses `pgvector` for semantic search embeddings). Pydantic schemas enforce validation before records enter the processed layer.

### Bicameral Term (2026-2031)

Starting with the term that began 2026-07-28, Congress is bicameral: a Senado and a Cámara de Diputados, replacing the single unicameral chamber of prior terms (2021-2026 and earlier). This affects several entities:

- Raw reference-data tables (`RawBancada`, `RawCommittee`, `RawCongresista`, `RawOrganization`) carry a `chamber` column recording which chamber a scraped row belongs to (`"Diputados"`, `"Senadores"`, or `None` for legacy/pre-bicameral rows that don't expose a chamber).
- Bill/motion ids for this term are chamber-suffixed (e.g. `"00006-2026-2031-S"`) instead of the legacy `"{year}_{number}"` shape; `chamber_label_from_id()` (`backend/process/utils.py`) resolves the chamber per-row from the id itself, so `Bill`/`Motion` records don't need their own `chamber` column.
- Committees can be joint/bicameral (members from both chambers, e.g. Comisión Bicameral de Presupuesto) — scraped with raw `chamber="Congreso"`, which `CHAMBER_LABEL_TO_ORG_NAME` (`backend/core/constants.py`) maps to no chamber parent, so the clean `Organization` row ends up parentless (`parent_org_id IS NULL`) rather than under either chamber. The clean `Organization` table itself has no `chamber` column — this reuses the existing single-parent schema instead of adding a distinct "shared committee" concept. See `Organization`, below.
- `Congresista.congresista_id` is a stable, national, cross-term/cross-chamber person identifier (distinct from the internal `Congresista.id` primary key) mined from bill/motion firmantes data, used to reliably match a reelected person's new-term row to their existing one regardless of which chamber they moved to.

## Data Sources

All data originates from publicly available information published by the Peruvian Congress (Congreso de la República):

| Source | Format | Content | Example |
|--------|--------|---------|---------|
| Congreso Website and internal API | HTML / Internal API | Bills, Motions, Committees, Congressmembers, etc | [Web Page example](https://www3.congreso.gob.pe/pagina/congresistas)<br> [API example](https://api.congreso.gob.pe/spley-portal-service/expediente/ICnrsvoH7U-3Sjp2uTAa2A/mCfgvwjVo-nSQEGbcovENg) |
| Documents related to Bills/Motions | Scanned PDF | Attendance and votes, bills/motions content, letters | [Attendance and Votes PDF example](https://api.congreso.gob.pe/spley-portal-service//archivo/NjYzMA==/pdf) <br> [Bill content example](https://api.congreso.gob.pe/spley-portal-service/archivo/OTQ=/pdf)|
| Live sessions streamings | Video / YouTube API | Plenary and Committee Sessions | [Plenary session video example](https://www.youtube.com/watch?v=sSmMGJ3nkHg&list=PLfVIxRaemgNrCGUfo6DrFjZmtFKgIq72Z&index=2&t=6288s) |

## Core Entities

This section includes the details on each core entity for the data model. All the core entities refers to cleaned, validated, and normalized entities ready for analysis and frontend consumption.

### AdminMembership

Tracks which congresista belongs to which administrative organization per legislative period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |

### Attendance

Records attendance at vote events. Unique on `(event_id, attendee_id)`.

| Column | Type | Key | Description |
|---|---|---|---|
| event_id | String | PK, FK → vote_events.vote_event_id | Vote event identifier |
| attendee_id | Integer | FK → congresistas.id | |
| status | String | | Present, absent, license |
| bancada_id | Integer (nullable) | FK → organizations.org_id | Attendee's bancada at the event date |

### AttendanceClarification

Records a correction to a member's recorded attendance, sourced from the president's clarification paragraph.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| event_id | String | FK → vote_events.vote_event_id | The vote event this clarification is about |
| voter_id | Integer (nullable) | FK → congresistas.id | Resolved congresista, if a match was found |
| member_name | String | | Raw name as printed/extracted, kept even when resolved |
| note | String | | Verbatim clarification text |
| roster_value | String (nullable) | | The member's value on the original roster |
| clarified_value | String (nullable) | | The corrected value |

### BancadaMembership

Tracks which congresista belongs to which bancada per legislative period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |

### Bill

Represents a bill (proyecto de ley). For the 2026-2031 bicameral term, `id` is chamber-suffixed (e.g. "00006-2026-2031-S"); legacy ids keep the "{year}_{number}" shape (e.g. "2021_3"). See [Bicameral Term](#bicameral-term-2026-2031).

| Column | Type | Key | Description |
|---|---|---|---|
| id | String | PK | Bill identifier |
| title | String | | Bill title |
| summary_congreso | String | | Bill summary from the Congress |
| observations | String | | Observations |
| status | String | | Current status |
| proponent | String | | Proponent type |
| author_id | Integer | FK → congresistas.id | Primary author |
| bill_approved | Boolean | | Whether the bill has been approved/published |
| summary_oc | String | | Summary generated by OpenCongress |
| pley_id | String | | ID for the Proyecto de Ley, as used internally by the parliament |
| bill_diff | Boolean | | True if the bill has ≥ 1 bill_differences row with difference_type in (first_version, no_change, modified); excludes unavailable/incomparable |
| votes | Boolean | | True if the bill has at least one complete and reviewed votation registry |

### BillCongresistas

Junction table linking bills to congresistas with their role. Composite PK on `(bill_id, person_id)`.

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | PK, FK → bills.id | A unique identifier for the bill. |
| person_id | Integer | PK, FK → congresistas.id | A unique identifier for the person. |
| bancada_id | Integer | FK → organizations.org_id | Unique identifier for the political group associated with the bill at the moment of presentation. |
| role_type | String | | Role: author, coauthor, adherente, etc. |

### BillOrganization

Represents the relation between bills and a organization, and keeps track of its
presentation and final decision date onf each organization (committee or chamber)

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | FK → bills.id | The identifier of the bill. |
| org_id | Integer | FK → organizations.org_id | The identifier of the organization. |
| org_type | str |  | Type of the organization.
| presentation_date | Date |  | Date of presentation of the motion in the organization.
| decision_date | Date |  | Date of the final decision of the motion in the organization.

### BillStep

Tracks the procedural history of a bill.

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | FK → bills.id | The identifier of the bill associated with this step. |
| step_id | Integer | PK | A unique identifier for each step record. |
| step_type | String | | Step type (e.g., vote, assigned to committee, presented) |
| vote_step | Boolean | | Records if the step is a vote or not.
| vote_event_id | String | FK → vote_events.vote_event_id | Id of the vote.
| step_date | DateTime | | Date the step occurred |
| step_detail | String | | Details of the step |

### BillText

Processed table: `bill_texts`.

Normative body sliced from each bill PDF: from the first matched heading (e.g. “PROYECTO DE LEY”, “EXPOSICIÓN DE MOTIVOS”) to the first trailing marker (e.g. “CONSEJO DIRECTIVO DEL CONGRESO”), if any. Heading/marker search is uppercase-only, so original casing and accents are preserved. Stores the content body of the bill in different steps of the legislative process.

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | PK, FK → bills.id | Bill |
| step_id | Integer | PK, FK → bill_steps.step_id | A unique identifier for each step record. |
| file_id | Integer | PK, FK → raw_bill_documents.file_id | A unique identifier for each file |
| version_id | Integer | PK | |
| text | String (nullable) | | Body slice, or null if no heading matched |

### BillDifference

Processed table: `bill_differences`.

Precomputed text diff between a bill step and the most recent text-bearing predecessor. One row per `BillStep`; `step_id` identifies the "new" version. `difference_content` holds the JSON-serialized hybrid diff payload (`parser_version`, `summary`, `nodes`) produced by the `backend/process/diff/` package; the renderer schema is documented in `compute_bill_difference` / `_build_payload` and consumed by the frontend per [`bill_difference_contract.md`](./bill_difference_contract.md).

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | PK, FK → bill_steps.bill_id | Bill |
| step_id | Integer | PK, FK → bill_steps.step_id | The "new" version step |
| prev_step_id | Integer (nullable) | | The previous text-bearing step (`step_id` within the same bill), or null for the first version |
| difference_type | String | | One of `modified`, `no_change`, `first_version`, `incomparable`, `unavailable` |
| difference_content | Text (nullable) | | JSON payload (structured diff) when `difference_type = "modified"`; null otherwise |

### ChamberMembership

Tracks which congresista belongs to which chamber per legislative period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |
| condicion | String | | Current status of their membership into the chamber |
| votes_in_election | Integer | | Votes obtained in the election |
| dist_electoral | String | | Electoral district |

### CommitteeMembership

Tracks which congresista belongs to which committee per legislative period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |

### Congresista

Represents a member of the peruvian parliament. Unique on `(full_name, dni)`.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| full_name | String |  | Full name of the person |
| first_name | String |  | First name of the person |
| last_name | String | | Last name of the person |
| dni | String | | National Identification Number of the person |
| gender | Integer | | Indicates the gender of the person |
| photo_url | String | | Official photo URL |
| photo_bytes | Binary (nullable) | | Downloaded portrait image bytes, when fetched (see `backend/scrapers/congresista_photos.py`) |
| website | String | | Official website URL |
| congresista_id | Integer (nullable) | Indexed | Stable, national, cross-term/cross-chamber person identifier mined from bill/motion firmantes data — not the same as `id`. Used by `find_congresista` as a reliable matching key ahead of fuzzy name matching. See [Bicameral Term](#bicameral-term-2026-2031). |

### CongresistaAlias

Alternate names used to match a congressperson (e.g. name variants seen across different scraped sources). Deleting a `Congresista` cascades to its aliases.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| congresista_id | Integer | FK → congresistas.id | The congresista this alias belongs to |
| name | String | UQ | Normalized alternate name |


### Ley

Represents an enacted law (ley).

| Column | Type | Key | Description |
|---|---|---|---|
| id | String | PK | Law identifier |
| title | String | | Law title |
| bill_id | String | | Bill that originated this law |


### Membership

Tracks a person's role in an organization during a time period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |

### Membership Polymorphism

Memberships use SQLAlchemy joined-table inheritance. The `memberships` table stores the fields shared by every membership record, and each specialized membership table stores only the fields that are specific to that organization type. The `org_type` column is the polymorphic discriminator configured with `polymorphic_on`.

| org_type | ORM class | Table |
|---|---|---|
| Bancada | BancadaMembership | bancada_memberships |
| Partido | PartyMembership | party_memberships |
| Cámara | ChamberMembership | chamber_memberships |
| Comisión | CommitteeMembership | committee_memberships |
| Administrativo | AdminMembership | admin_memberships |

Each subtype table uses the same `id` as the base row through a primary-key foreign key to `memberships.id`. In practice, inserting a `BancadaMembership` creates one row in `memberships` and one row in `bancada_memberships` with the same identifier. `ChamberMembership` is currently the only subtype with extra columns: `condicion`, `votes_in_election`, and `dist_electoral`.

The processing layer calls `upsert_membership()`, which maps the normalized `org_type` value to the correct ORM subclass before inserting or updating the record. Querying the base `Membership` model can return polymorphic ORM instances, while querying a subtype such as `CommitteeMembership` restricts results to that subtype.

### Motion

Represents a motion (moción).

| Column | Type | Key | Description |
|---|---|---|---|
| id | String | PK | Motion identifier |
| motion_type | String| | Type of motion |
| summary_congreso | String | | Summary of the motion. |
| observations | String | | Observations |
| status | String | | Current status |
| author_id | Integer | FK → congresistas.id | Primary author |
| motion_approved | Boolean | | Whether the motion has been approved |
| summary_oc | String | | Summary generated by OpenCongress |

### MotionCongresistas

Represents a relation between a motion and parliament members based on their role during the presentation of the motion.

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK, FK → motions.id | A unique identifier for the motion. |
| person_id | Integer | PK, FK → congresistas.id | Name of the person. |
| role_type | String | | Role: author, coauthor, adherente, etc. |
| bancada_id | Integer | PK, FK → organizations.org_id | Unique identifier for the political group associated with the motion at the moment of presentation. |


### MotionOrganization

Represents the relation between motions and an organization such as the 'Cámara
de Diputados' or 'Cámara de Senadores'

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK, FK → motions.id | The identifier of the motion. |
| org_id | Integer | PK, FK → organizations.org_id | The identifier of the organization.
| org_type | String | | Type of the organization.
| presentation_date | Date | | Date of presentation of the motion in the organization.
| decision_date | Date | | Date of the final decision of the motion in the organization.


### MotionStep

Tracks the procedural history of a motion.

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK, FK → motions.id | |
| step_id | Integer | PK | |
| step_type | String | | Step type |
| vote_step | Boolean | | Records if the step is a vote or not.
| vote_event_id | String | FK → vote_events.vote_event_id | Id of the vote.
| step_date | DateTime | | Date the step occurred |
| step_detail | String | | Details of the step |

### MotionText

Processed table: `motion_texts`.

Normative body sliced from each motion PDF.

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK, FK → motions.id | The identifier of the motion associated with this step. |
| step_id | Integer | PK, FK → motion_steps.step_id | A unique identifier for each step record. |
| file_id | Integer | PK, FK → raw_motion_documents.file_id | A unique identifier for each file |
| version_id | Integer | PK | The version of the motion's content |
| text | String (nullable) | | Extracted text from the file |


### Organization

Represents legislative organizations: committees, bancadas, parties, chambers and administratives (Junta de Portavoces, Consejo Directivo, Mesa Directiva, Comisión Permanente). Uniqueness on `(org_name, org_type, parent_org_id)` — since `parent_org_id` is part of the key, a Senado org and a same-named Diputados org are distinct rows (see [Bicameral Term](#bicameral-term-2026-2031)); a parentless joint/bicameral committee (`parent_org_id IS NULL`) is likewise distinguished from any chamber-scoped committee of the same name.

`org_subtype` is constrained by a `CHECK` tied to `org_type`: when `org_type = "Comisión"`, it must be one of `TypeCommittee`'s values (`Comisiones Investigadoras`, `Grupo de Trabajo`, `Subcomisión de Acusaciones Constitucionales`, `Subcomisión de Control Político`, `Comisión de Levantamiento de Inmunidad Parlamentaria`, `Comisión Ordinaria`, `Comisión Ordinaria Legislativa`, `Comisión Ordinaria No Legislativa`, `Comisión Bicameral`, `Sub Comisión de Seguimiento del TLC`, `Comisiones Especiales`, `Comisión de Ética Parlamentaria` — the Legislativa/No Legislativa split and `Comisión Bicameral` are 2026-2031 additions; legacy committees keep the generic `Comisión Ordinaria` value); when `org_type = "Administrativo"`, it must be one of `TypeAdmin`'s values (`Junta de Portavoces`, `Mesa Directiva`, `Comisión Permanente`, `Consejo Directivo`); for every other `org_type` it must be `NULL`.

| Column | Type | Key | Description |
|---|---|---|---|
| org_id | Integer | PK | Auto-increment |
| org_name | String | UQ | Organization name |
| org_type | String | UQ | Organization type |
| org_subtype | String (nullable) | | Organization subtype, if applicable — see constraint above |
| org_short_name | String (nullable) | | Shortened name, for special committees |
| org_link | String | | Website URL |
| parent_org_id | Integer (nullable) | UQ, FK → organizations.org_id | The organization's parent, if any. `NULL` for top-level orgs (chambers, parties, and joint/bicameral committees) |
| date_founding | DateTime (nullable) | | Date of establishment of the organization if applicable |
| date_dissolution | DateTime (nullable) | | Date of dissolution of the organization if applicable |

### PartyMembership

Tracks which congresista belongs to which party per legislative period.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increments |
| person_id | Integer | FK → congresistas.id | Identifier for the person |
| org_id | Integer | FK → organizations.org_id | Identifier for the organization |
| leg_period | String | | Legislative period |
| org_type | String | | Type of membership/organization |
| role | String | | Role of the person in the organization |
| start_date | DateTime | | Start of membership |
| end_date | DateTime | | End of membership |



### VoteEvent

Represents a vote event in a plenary session. Unique on `(leg_period, bill_or_motion, bill_motion_id, date)`.

| Column | Type | Key | Description |
|---|---|---|---|
| vote_event_id | String | PK | Stable vote event identifier |
| org_id | Integer | FK → organizations.org_id | Unique identifier for the organization where the vote event occur
| bill_id | String | FK → bills.id | Unique identifier for the bill associated with the vote.
| motion_id | String | FK → motions.id | Unique identifier for the motion associated with the vote.
| event_date | Date |  | The date of the vote event.
| result | String |  | Final result of the vote event
| votes_in_favor | Integer |  | Number of votes in favor
| votes_against | Integer |  | Number of votes against
| votes_abstention | Integer |  | Number of votes in abstention

### Vote

Records how each congresista voted. Unique on `(vote_event_id, voter_id)`.

| Column | Type | Key | Description |
|---|---|---|---|
| vote_event_id | String | PK, FK → vote_events.vote_event_id | |
| voter_id | Integer | FK → congresistas.id | |
| option | String | | Vote cast: yes, no, abstain |
| bancada_id | Integer | FK → organizations.org_id | Voter's bancada at time of vote |

### VoteCounts

Pre-aggregated vote counts by bancada. Composite PK on `(vote_event_id, option, bancada_id)`.

| Column | Type | Key | Description |
|---|---|---|---|
| vote_event_id | String | PK, FK → vote_events.vote_event_id | Unique identifier for the vote event. |
| option | String | PK | Vote option |
| bancada_id | Integer | PK, FK → organizations.org_id | The political group of the voter. |
| count | Integer | | Number of votes for the option. |

### VoteClarification

Records a correction to a member's recorded vote, sourced from either the president's clarification paragraph or a standalone member letter.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| vote_event_id | String | FK → vote_events.vote_event_id | The vote event this clarification is about |
| voter_id | Integer (nullable) | FK → congresistas.id | Resolved congresista, if a match was found |
| member_name | String | | Raw name as printed/extracted, kept even when resolved |
| source | String | | Either `president_note` or `member_letter` |
| note | String | | Verbatim clarification text |
| roll_value | String (nullable) | | The member's value on the original roll |
| clarified_value | String (nullable) | | The corrected value |

### MemberLetter

A standalone letter (oficio) from a member registering their intended attendance and/or vote for a specific bill or motion. Exactly one of `bill_id`/`motion_id` is set.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| bill_id | String (nullable) | FK → bills.id | Bill this letter is about, if any |
| motion_id | String (nullable) | FK → motions.id | Motion this letter is about, if any |
| voter_id | Integer (nullable) | FK → congresistas.id | Resolved congresista, if a match was found |
| member_name | String | | Raw name as printed/extracted, kept even when resolved |
| party | String (nullable) | | Party as printed on the letter, if present |
| letter_date | Date (nullable) | | Date on the letter |
| subject_reference | String | | The bill/motion subject text referenced by the letter |
| requested_attendance | String (nullable) | | Attendance status requested, if any |
| requested_vote | String (nullable) | | Vote option requested, if any |

### CongresistaMetric

Processed table: `congresista_metrics`.

Stores derived metrics for each congresista and legislative period. Rows are rebuilt from chamber memberships, vote attendance, authored bills, and authored motions.

| Column | Type | Key | Description |
|---|---|---|---|
| cong_id | Integer | PK, FK → congresistas.id | Congresista identifier |
| leg_period | String | PK | Legislative period |
| avg_attendance | Float | | Share of vote events attended in the period |
| bills_auth | Integer | | Number of authored bills |
| bills_success_rate | Float | | Share of authored bills approved |
| motions_auth | Integer | | Number of authored motions |
| motions_success_rate | Float | | Share of authored motions approved |

### SemanticBill

Processed table: `semantic_bills`.

`semantic_bills` is a rebuildable derived table. Each row represents one chunk of assembled bill text and the embedding generated from that chunk. The table should be regenerated whenever the chunking strategy, text assembly logic, or embedding model changes. Because it is derived from processed bill data, rows can be safely deleted and recreated as long as the source tables remain available. This table is not the source of truth for bill metadata or document text.

The HNSW vector index for `embedding` is managed outside the SQLAlchemy model. Regular constraints and lookup indexes are part of the model definition, but the vector index is created operationally after large loads or full rebuilds. This avoids the cost of maintaining the HNSW graph during bulk inserts while keeping semantic search fast for normal incremental updates.

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment row identifier |
| bill_id | String | FK → bills.id | Bill associated with the chunk |
| chunk_index | Integer | UQ with bill/model | Chunk position within the assembled bill text |
| text | Text | | Text embedded for search |
| embedding | Vector | | Embedding vector, currently dimension 768 |
| embedding_model_name | String | UQ with bill/chunk | Embedding model, currently `intfloat/multilingual-e5-base` |

## Raw Database - Raw Layer

This section includes the details on each raw entity for the raw data model. All the raw entities refers to the raw data as were fetched from the original source.

### Common Metadata Columns

Every table in the Raw Layer includes:

| Column | Type | Description |
|---|---|---|
| timestamp | DateTime | When the scraping task ran for the record |
| last_update | Boolean | Whether this row is the most recent scrape for its entity |
| changed | Boolean | Whether this scrape differs from the previous one |
| processed | Boolean | Whether this row has been processed into the processed layer |

### ScraperRun 
Stores the metadata on the scrapers jobs for future analysis and future pipeline automations.

These records are stored on the table `scraper_runs` with the following columns:

| Column | Type | Key | Description |
|--------|------|-----|-------------|
| run_id | int | PK | Unique identifier of the scraper run (auto-increment) |
| scraper_name | String | | Name of the scraper file that ran |
| start_time | DateTime | | Time when the scraper started running |
| end_time | DateTime | | Time when the scraper stop running |
| scraped_rows | Integer | | Number of rows scraped within the run |

### ModelCostLedger

Cumulative real spend for one LLM model, used to enforce a persistent budget cap on pipelines that call out to a paid model API (e.g. the votes extractor). Provider-agnostic: `model` alone is the primary key, so any caller sharing a model name shares the same running total.

These records are stored on the table `model_cost_ledger` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| model | String | PK | Model identifier (e.g. "gpt-5.6-luna") |
| provider | String (nullable) | | Descriptive provider name (e.g. "openai", "anthropic") — metadata only, not part of the key |
| total_cost_usd | Float | | Cumulative real spend recorded for this model |
| updated_at | DateTime | | Timestamp of the last increment |


### RawBancada 
Stores scraped results from the Congress website endpoint for the list of bancadas (political groups).

- Original source: The bancadas' list [web page](https://www3.congreso.gob.pe/pagina/grupos-parlamentarios).

These records are stored on the table `raw_bancadas` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| legislative_period | String | | Legislative period |
| chamber | String (nullable) | | Raw chamber label as scraped (e.g. "Diputados"/"Senadores"); `NULL` for legacy/pre-bicameral rows that don't expose a chamber. See [Bicameral Term](#bicameral-term-2026-2031). |
| raw_html | String | | Full HTML content |

### RawBill 

Stores scraped results from the Internal API for Bills (Proyectos de Ley) from the Congress website. 

- Original source: A web page with this structure: https://wb2server.congreso.gob.pe/spley-portal/#/expediente/2021/14326
- Internal API: A JSON endpoint visible in the browser network activity. [See example](https://api.congreso.gob.pe/spley-portal-service/expediente/ICnrsvoH7U-3Sjp2uTAa2A/eZnTrOVGU68ZlxU_zj9XrA). 

These records are stored on the table `raw_bills` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | String | PK | Bill identifier (e.g., "2021_1234", or "00006-2026-2031-S" for the bicameral term) |
| general | String | | Main bill info (HTML/text) |
| committees | String (nullable) | | Mined from the API's `estudioComisiones` field. Legitimately empty/null for most bills — it only fills in once a committee formally studies the bill. Not the source for a bill's committee-assignment history; that comes from `steps` (see `BillStep`, above). |
| congresistas | String | | Author and proponent info |
| steps | String | | Legislative step info |
| api_url | String (nullable) | | Resolved Congress internal API URL used to fetch this row |

### RawBillDocument 

Stores metadata from PDF documents linked to bills. These documents were extracted from the `RawBill.steps` column.

- Original source: A PDF document like this: https://api.congreso.gob.pe/spley-portal-service//archivo/NjYzMA==/pdf

These records are stored on the table `raw_bill_documents` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | PK | Reference to the bill |
| step_id | Integer | PK | Event identifier |
| file_id | String | PK | Document file identifier |
| step_date | DateTime |  | Date of the related event |
| url | String | | Document URL |
| s3_key | String | | Key that maps the location of the document on the AWS S3 Bucket |
| local_path | String | | Local path where the document is located. |
| file_size | Float (nullable) | | Document file size |
| num_pages | Integer (nullable) | | Number of pages in the document |

### RawBillPage

Stores metadata from each page of the documents linked to bills. These pages were extracted from the `RawBillDocument.url`, `RawBillDocument.s3_key` or `RawBillDocument.local_path`.

These records are stored on the table `raw_bill_pages` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| bill_id | String | PK | Reference to the bill |
| step_id | Integer | PK | Event identifier |
| file_id | String | PK | Document file identifier |
| page_num | Integer | PK | Page of the document |
| text | String |  | Text content of the page |
| ocr_model | String |  | OCR engine used to extract this page (`chandra2` for bills, `Tesseract` for attendance/votes) |

### RawCommittee 

Stores scraped results from the Congress website endpoint for the list of committees.

- Original source: The committees' list [web page](https://www3.congreso.gob.pe/pagina/comisiones-ordinarias).

These records are stored on the table `raw_committees` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| legislative_year | String | | Legislative year |
| chamber | String (nullable) | | Raw chamber label as scraped (e.g. "Diputados"/"Senadores"), or `"Congreso"` for a joint/bicameral committee. `NULL` for legacy/pre-bicameral rows. See [Bicameral Term](#bicameral-term-2026-2031). |
| committee_type | String | | Type of committee |
| raw_html | String | | Full HTML content |

### RawCongresista 

Stores scraped results from the Congress website endpoint for the list of congressmembers. 

- Original source: The congressmembers' list [web page](https://www3.congreso.gob.pe/pagina/congresistas) and each congressmember's [membership page](https://www3.congreso.gob.pe/congresistas2021/GrimanezaAcuna/sobrecongresista/cargos/)
- Internal API: A JSON endpoint visible in the browser network activity. [See example](for each congressmember https://wb2server.congreso.gob.pe/vll/cargos/api/2021/16751831). 

These records are stored on the table `raw_congresistas` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| leg_period | String | | Legislative period |
| chamber | String (nullable) | | Raw chamber label as scraped (e.g. "Diputados"/"Senadores"). `NULL` for legacy/pre-bicameral rows, which don't expose a chamber via this dropdown at all. See [Bicameral Term](#bicameral-term-2026-2031). |
| website | String | | Congressperson's website URL |
| profile_content | String | | HTML from the profile tab |
| memberships_content | String | | API response for memberships (JSON) |

### RawLey 
Stores scraped results from the Congress website endpoint for the historic Laws that have being approved.

- Original source: Internal API from the Congress website with the following structure https://api.congreso.gob.pe/adlp-visor-service/expediente/ley?numley=31555

These records are stored on the table `raw_leyes` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| data | String | | Raw XML data for the law |

### RawMotion 
Stores scraped results from the Internal API for Motions (Mociones) from the Congress website. 

- Original source: A web page with this structure: https://wb2server.congreso.gob.pe/smociones-portal/#/expediente/2021/21804
- Internal API: A JSON endpoint visible in the browser network activity. [See example](https://api.congreso.gob.pe/smociones-portal-service/mocion/2021/21804). 

These records are stored on the table `raw_motions` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | String | PK | Motion identifier |
| general | String | | Main motion info |
| congresistas | String | | Author and proponent info |
| steps | String | | Motion steps info |

### RawMotionDocument 

Stores metadata from PDF documents linked to motions. These documents were extracted from the `RawMotion.steps` column.
These records are stored on the table `raw_motion_documents` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK | Reference to the motion |
| step_id | Integer | PK | Event identifier |
| file_id | String | PK | Document file identifier |
| step_date | DateTime |  | Date of the related event |
| url | String | | Document URL |
| s3_key | String | | Key that maps the location of the document on the AWS S3 Bucket |
| local_path | String | | Local path where the document is located. |
| file_size | Float (nullable) | | Document file size |
| num_pages | Integer (nullable) | | Number of pages in the document |

### RawMotionPage

Stores metadata from each page of the documents linked to motions. These pages were extracted from the `RawMotionDocument.url`, `RawMotionDocument.s3_key` or `RawMotionDocument.local_path`.

These records are stored on the table `raw_motion_pages` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| motion_id | String | PK | Reference to the motion |
| step_id | Integer | PK | Event identifier |
| file_id | String | PK | Document file identifier |
| page_num | Integer | PK | Page of the document |
| text | String |  | Text content of the page |
| ocr_model | String |  | OCR engine used to extract this page (`chandra2` for bills, `Tesseract` for attendance/votes) |

### RawOrganization 
Stores scraped results from the Congress website endpoint for the organizational bodies such as Junta de Portavoces, Consejo Directivo, Mesa Directiva, and Comisión Permanente.

- Original source: Web pages for the [Junta de Portavoces](https://www3.congreso.gob.pe/pagina/junta-de-portavoces), [Consejo Directivo](https://www3.congreso.gob.pe/pagina/consejodirectivo), [Mesa Directiva](https://www3.congreso.gob.pe/pagina/mesa-directiva) and [Comisión Permanente](https://www3.congreso.gob.pe/pagina/comision-permanente).

These records are stored on the table `raw_organizations` with the following columns:

| Column | Type | Key | Description |
|---|---|---|---|
| id | Integer | PK | Auto-increment |
| legislative_year | String | | Legislative year |
| chamber | String (nullable) | | Raw chamber label as scraped (e.g. "Diputados"/"Senadores"). `NULL` for legacy/pre-bicameral rows. See [Bicameral Term](#bicameral-term-2026-2031). |
| type_org | String | | Organization type |
| org_link | String (nullable) | | Organization website URL |
| raw_html | String | | Full HTML content |
