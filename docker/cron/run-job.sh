#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <make-target>" >&2
    exit 2
fi

. /app/.cron-env
cd /app

target="$1"
date=$(date +%Y-%m-%d)

case "$target" in
    scrape-*)
        log_dir="/app/logs/scrapers/$date"
        ;;
    *)
        log_dir="/app/logs/process/$date"
        ;;
esac

mkdir -p "$log_dir"

log_file="$log_dir/${target}.log"
json_file="$log_dir/${target}.json"

started_at=$(date -Iseconds)
start_epoch=$(date +%s)

status="success"
exit_code=0

{
    echo "========================================"
    echo "$(date -Iseconds) starting ${target}"

    if make "$target"; then
        echo "$(date -Iseconds) finished ${target} successfully"
    else
        exit_code=$?
        status="failed"
        echo "$(date -Iseconds) failed ${target} with exit code ${exit_code}"
    fi

    finished_at=$(date -Iseconds)

    duration=$(( $(date +%s) - start_epoch ))

    cat > "$json_file" <<EOF
{
  "job": "$target",
  "started_at": "$started_at",
  "finished_at": "$finished_at",
  "status": "$status",
  "exit_code": $exit_code,
  "duration_seconds": $duration
}
EOF

    echo "duration_seconds=${duration}"
    echo "========================================"
    echo

    exit "$exit_code"

} >> "$log_file" 2>&1