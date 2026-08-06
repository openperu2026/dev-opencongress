import json
from pathlib import Path

from backend.config import directories

PROMPTS_DIR = directories.ROOT_DIR / "backend" / "process" / "votes"

DEFAULT_MODEL = "gpt-5.6-luna"

# A fixed prompt_cache_key shared by every request. Because system_prompt +
# user_prompt are byte-identical on every call (no per-document
# interpolation), this string identifies one reusable prefix that OpenAI's
# cache router can key on across models and across batches.
PROMPT_CACHE_KEY = "congress-extraction-v3"

# Models that support explicit prompt_cache_breakpoint / prompt_cache_options.
# Models before this family actively REJECT these fields with a 400 error --
# it's not a harmless no-op -- so this stays an explicit allow-list.
EXPLICIT_BREAKPOINT_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}

SYSTEM_PROMPTS = {
    "bill": Path(PROMPTS_DIR / "system_prompt_bills.md").read_text(encoding="utf-8"),
    "motion": Path(PROMPTS_DIR / "system_prompt_motions.md").read_text(
        encoding="utf-8"
    ),
}
USER_PROMPTS = {
    "bill": Path(PROMPTS_DIR / "user_prompt_bills.md").read_text(encoding="utf-8"),
    "motion": Path(PROMPTS_DIR / "user_prompt_motions.md").read_text(encoding="utf-8"),
}
EXTRACTION_SCHEMA = json.loads(
    Path(PROMPTS_DIR / "extraction_schema.json").read_text(encoding="utf-8")
)

BATCH_JOBS_DIR = PROMPTS_DIR / "batch_jobs"

# $ per 1,000,000 tokens, STANDARD (non-batch), SHORT-CONTEXT (<270K tokens)
# rates. cache_write only applies to GPT-5.6+ models (pre-5.6 cache writes
# are free, so those rows simply omit the key and default to $0 via .get()).
PRICING_PER_MILLION = {
    "gpt-4.1": {"input": 2.00, "cached_input": 1.00, "output": 8.00},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-5.6-luna": {
        "input": 0.20,
        "cached_input": 0.02,
        "cache_write": 0.25,
        "output": 1.20,
    },
}

# The Batch API discounts every token category (input, cached input, output)
# by 50% relative to the synchronous rate above.
BATCH_DISCOUNT = 0.5
