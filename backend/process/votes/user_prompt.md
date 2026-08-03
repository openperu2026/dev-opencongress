# USER PROMPT (template)

Attached is a PDF issued by the Congreso de la República del
Perú. It contains one or more session bundles, each potentially made up of an
attendance page, a voting page, a plenary-minutes excerpt, and/or individual
congressperson letters (oficios) about a specific vote.

Extract the full structured record following your system instructions exactly,
including:
- the complete roster/roll for every attendance and voting page (reconstructed
  correctly across the 3-column layout — do not scramble columns),
- both summary tables on each page (overall totals and per-party breakdown),
- any clarification paragraph or member letter, applied per the override rules
  in your instructions,
- the narrative minutes pages, split into discrete events with their vote counts.

Return only the JSON object described in your schema. If a value cannot be
determined confidently, use `null` and list it in `_uncertain_fields` — do not
guess or silently omit a member.