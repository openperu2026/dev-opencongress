# USER PROMPT (template)

Attached is a PDF issued by the Congreso de la República del Perú. It may
contain votes/attendance for more than one bill if a whole session's acta was
bundled into one file — a separate message accompanying this one names the
specific `pley_id` and `sumilla` this extraction is scoped to. Use that to
find and extract only the material relevant to that bill, per your system
instructions.

Extract the full structured record, including:
- the complete roster/roll for every relevant attendance and voting page
  (reconstructed correctly across the 3-column layout — do not scramble
  columns),
- both summary tables on each relevant page (overall totals and per-party
  breakdown),
- any clarification paragraph or member letter about this bill, applied per
  the override rules in your instructions,
- the narrative minutes events about this bill, each with its stated outcome
  and vote counts.

Return only the JSON object described in your schema. If a value cannot be
determined confidently, use `null` and list it in `_uncertain_fields` — do not
guess or silently omit a member. If the given pley_id isn't in this document
at all, set `match_found: false` and leave the arrays empty.