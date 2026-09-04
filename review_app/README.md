# Vote & Attendance Review Tool

A local-only Flask app for reviewing vote/attendance records extracted by
`backend/process/votes/` against their source PDF, and correcting them in
place.

**This app is never deployed publicly.** It has direct DB write access and
no authentication — that's intentional (it's for one person, run locally),
not a gap to fill in later. It's a separate app from `app/` (the public
OpenCongress site) specifically to keep it off the internet.

## Setup

Uses the same `.env`/`DB_URL` as the rest of the repo — nothing extra to
configure if you already run `backend`/`app` locally. See the repo root
`README.md` for DB setup instructions.

## Running

```bash
uv run python -m review_app
```

Starts on `http://127.0.0.1:5050` by default. Override with:

- `REVIEW_APP_PORT` — port (default `5050`)
- `REVIEW_APP_HOST` — bind address (default `127.0.0.1`)
- `REVIEW_APP_SECRET_KEY` — Flask session signing key (a local default is
  used if unset; fine for a tool nobody else can reach)

**`REVIEW_APP_HOST` will refuse to bind to anything other than
`127.0.0.1`/`localhost`/`::1`** unless `REVIEW_APP_ALLOW_REMOTE=1` is
explicitly set. This isn't a suggestion — it's the one thing standing
between "local tool" and "unauthenticated production-data-write endpoint
on the internet." Don't set `REVIEW_APP_ALLOW_REMOTE` unless you've added
your own access control in front of this app.

## Using it

1. Open `/review`, search for a vote event by ID, bill/motion ID, date
   range, or org.
2. Open a result to see the source PDF next to the vote/attendance table,
   side by side. The table always shows the **full expected roster** —
   everyone who was a member of the org the vote happened in as of that
   date — not just the people the extraction actually found a vote for,
   so a missed congresista is visible (blank) instead of invisible.
   Anyone the extraction attributed a vote to who *isn't* in that
   expected roster still shows up too, so a wrong-person error stays
   visible instead of disappearing.
3. A summary panel at the top tallies vote counts by party and option
   live from the table's current state (including any unsaved-but-loaded
   corrections), with an "unrecorded" bucket per party.
4. Toggle **Edit Mode** to make the table editable — off by default, and
   turning it off also stops the form from submitting anything (browsers
   never send disabled fields).
5. Change a value, flag a row, or mark it verified, then **Save changes**.
   Selecting **"— not recorded —"** on an existing value removes that
   vote/attendance row entirely (the same mechanism covers both
   "correct" and "remove"). Every correction, addition, and removal is
   logged with who made it and when.
6. Missing someone the automatic roster didn't catch? Use the **"Add a
   congresista"** control at the bottom of the table to add anyone by
   name with a vote and/or attendance value, independent of the computed
   roster.
7. First visit asks for your name once per session — it's attribution for
   the change log, not a password.

## Running the tests

```bash
uv run pytest tests/database/test_review_crud.py tests/review_app/test_routes.py
```
