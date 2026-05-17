def build_bancada_bars(bancada_votes):
    bar_x = 140
    bar_max_width = 520
    row_height = 44

    sorted_rows = sorted(
        bancada_votes.items(),
        key=lambda item: (-item[1]["total"], item[0]),
    )

    max_total = max((counts["total"] for _, counts in sorted_rows), default=0)
    width_scale = bar_max_width / max_total if max_total else 0

    rows = []
    for index, (name, counts) in enumerate(sorted_rows):
        y = 22 + index * row_height

        segments = []
        offset = 0
        for key in ("yes", "no", "abstain"):
            width = counts[key] * width_scale
            if width <= 0:
                continue
            segments.append(
                {
                    "key": key,
                    "x": bar_x + offset,
                    "width": width,
                }
            )
            offset += width

        total_width = max(offset, 2)
        rows.append(
            {
                "name": name,
                "yes": counts["yes"],
                "no": counts["no"],
                "abstain": counts["abstain"],
                "total": counts["total"],
                "y": y,
                "bar_x": bar_x,
                "total_x": bar_x + total_width + 10,
                "segments": segments,
            }
        )

    chart_height = max(10, len(rows) * row_height + 18)
    return rows, chart_height
