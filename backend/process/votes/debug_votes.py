import sys

from openai import OpenAI
from backend.config import settings

BATCH_ID = (
    sys.argv[1] if len(sys.argv) > 1 else "batch_6a6d1158860c8190b92ca21236097059"
)

client = OpenAI(api_key=settings.OPENAI_API_KEY)
batch = client.batches.retrieve(BATCH_ID)

print(f"status: {batch.status}")
print(f"request_counts: {batch.request_counts}")
print(f"errors field on batch object: {batch.errors}")  # validation-time errors, if any
print()

if batch.error_file_id:
    content = client.files.content(batch.error_file_id).text
    print("---- error file contents ----")
    for line in content.splitlines():
        if line.strip():
            print(line)
else:
    print(
        "No error_file_id on this batch. If request_counts.failed > 0 but there's "
        "no error file, check batch.errors above and the output file (if any) -- "
        "some failure modes report per-line inside the output file's `error` key "
        "instead of a separate error file."
    )

if batch.output_file_id:
    print("\n---- output file contents (first 2000 chars) ----")
    out_content = client.files.content(batch.output_file_id).text
    print(out_content[:2000])
