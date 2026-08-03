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

start_time=$(date -Iseconds)
start_epoch=$(date +%s)

{
    echo "========================================"
    echo "${start_time} starting ${target}"

    if make "$target"; then
        status=0
        echo "$(date -Iseconds) finished ${target} successfully"
    else
        status=$?
        echo "$(date -Iseconds) failed ${target} with exit code ${status}"
    fi

    end_epoch=$(date +%s)
    duration=$((end_epoch - start_epoch))

    echo "duration_seconds=${duration}"
    echo "========================================"
    echo

    exit "$status"
} >> "$log_file" 2>&1