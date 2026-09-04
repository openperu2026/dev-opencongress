import argparse

from backend.database.orchestrator import OpenPeruOrchestrator
from backend.core.enums import LegPeriod


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenPeru ETL Orchestrator")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Run scrapers before processing for rows with last scrape older than 1 day",
    )
    parser.add_argument(
        "--skip-processing",
        action="store_true",
        help="Do not run raw->clean processing",
    )
    parser.add_argument(
        "--only-current",
        action="store_true",
        help="Scrape only current period where supported",
    )
    target_group = parser.add_mutually_exclusive_group()
    target_group.add_argument(
        "--only-bills",
        action="store_true",
        help="Run only bills scraping/processing",
    )
    target_group.add_argument(
        "--only-motions",
        action="store_true",
        help="Run only motions scraping/processing",
    )
    target_group.add_argument(
        "--only-leyes",
        action="store_true",
        help="Run only leyes scraping/processing",
    )
    target_group.add_argument(
        "--only-others",
        action="store_true",
        help="Run only non-bill/non-motion entities (congresistas, bancadas, organizations)",
    )
    target_group.add_argument(
        "--scrape-documents",
        action="store_true",
        help="Scrape pending bill/motion documents",
    )
    parser.add_argument(
        "--upload-s3",
        action="store_true",
        help="Upload existing and newly scraped bill/motion documents to S3",
    )
    parser.add_argument(
        "--process-documents",
        action="store_true",
        help="Enable document processing stage",
    )
    parser.add_argument(
        "--first-summary",
        action="store_true",
        help=(
            "Backfill mode: computes the first processing of bill summaries "
            "and semantic embeddings for every eligible row, and seeds the "
            "first-ever 2026-2031 chamber/party/bancada/admin-org "
            "membership per person with the confirmed real term-start date "
            "(2026-07-28) instead of the scrape timestamp. Legacy "
            "memberships and already-recorded 2026-2031 memberships are "
            "unaffected either way."
        ),
    )
    parser.add_argument(
        "--leg-period",
        choices=[p.value for p in LegPeriod],
        default=None,
        help=(
            "PROCESSING: restricts congresistas/bancadas/organizations "
            "processing to a single legislative period (e.g. 2026-2031). "
            "Default (None) processes all processable periods, unchanged; any "
            "explicit value narrows to just that period. SCRAPING (bills/"
            "motions): does NOT restrict the legacy scrape (it always runs "
            "with --scrape, regardless of this flag, since old bills/motions "
            "can still gain new documents/votes/status) -- it only controls "
            "whether the ADDITIONAL current-period (settings.LEG_PERIOD, "
            "'2026-2031') chamber-specific range scrapers also run: they "
            "run when this is None (default) or explicitly the current "
            "period, and are skipped for any other value. SCRAPING "
            "(congresistas/bancadas/committees/organizations): the "
            "OPPOSITE of bills/motions -- this legacy reference data is now "
            "historical/stable, so it is skipped by default and only runs "
            "when this flag is explicitly set to a period OTHER than the "
            "current one (e.g. '2021-2026'); the current-period chamber "
            "scrape runs when this is None (default) or explicitly the "
            "current period, same gating shape as bills/motions' chamber "
            "block, but the two never run in the same call -- exactly one of "
            "the two runs, unlike bills/motions where both may run together. "
            "Leyes processing/scraping is unaffected either way -- there is no "
            "bicameral concept for leyes. Chamber for bills/motions is always "
            "resolved per-row from the bill/motion's own id, not from this flag."
        ),
    )
    parser.add_argument(
        "--only-votes",
        action="store_true",
        help="Run vote extraction (sync) + load stage for bills and motions",
    )
    parser.add_argument(
        "--skip-vote-extraction",
        action="store_true",
        help="Skip the extraction of votes and attendance",
    )
    parser.add_argument(
        "--votes-limit",
        type=int,
        default=None,
        help="Max documents/pages to process per vote extraction/load call",
    )
    parser.add_argument(
        "--votes-max-pages",
        type=int,
        default=5,
        help="Only extract vote documents with at most this many pages",
    )
    parser.add_argument(
        "--votes-model",
        default="gpt-5.6-luna",
        help="OpenAI model to use for vote extraction",
    )
    parser.add_argument(
        "--votes-max-cost-usd",
        type=float,
        default=5.0,
        help=(
            "Persistent USD budget for this model (tracked cumulatively across "
            "runs) -- sync extraction stops before the next document once "
            "reached; batch submission stops queuing once an estimate would "
            "exceed it"
        ),
    )
    parser.add_argument(
        "--submit-vote-batches",
        choices=["bill", "motion"],
        default=None,
        help="Submit a historical-backfill Batch API job for vote extraction, then exit",
    )
    parser.add_argument(
        "--collect-vote-batches",
        metavar="BATCH_ID",
        default=None,
        help="Poll+collect a previously submitted vote-extraction batch by id, then exit",
    )
    parser.add_argument(
        "--collect-kind",
        choices=["bill", "motion"],
        default="bill",
        help="Required alongside --collect-vote-batches",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    orchestrator = OpenPeruOrchestrator()

    if args.submit_vote_batches:
        manifest = orchestrator.submit_vote_batches(
            kind=args.submit_vote_batches,
            model=args.votes_model,
            max_pages=args.votes_max_pages,
            limit=args.votes_limit,
            max_cost_usd=args.votes_max_cost_usd,
        )
        print(manifest)
        return

    if args.collect_vote_batches:
        orchestrator.collect_vote_batches(
            batch_id=args.collect_vote_batches,
            kind=args.collect_kind,
            model=args.votes_model,
        )
        return

    run_bills = True
    run_motions = True
    run_leyes = True
    run_others = True
    run_documents = True
    run_votes = True

    if args.only_bills:
        run_motions = False
        run_others = False
        run_leyes = False
        run_documents = False
        run_votes = False
    elif args.only_motions:
        run_bills = False
        run_others = False
        run_leyes = False
        run_documents = False
        run_votes = False
    elif args.only_leyes:
        run_motions = False
        run_bills = False
        run_others = False
        run_documents = False
        run_votes = False
    elif args.only_others:
        run_bills = False
        run_motions = False
        run_leyes = False
        run_documents = False
        run_votes = False
    elif args.scrape_documents:
        run_bills = False
        run_motions = False
        run_leyes = False
        run_others = False
        run_votes = False
    elif args.only_votes:
        run_bills = False
        run_motions = False
        run_leyes = False
        run_others = False
        run_documents = False

    if args.scrape:
        orchestrator.run_scrapers(
            scrape_bills=run_bills,
            scrape_motions=run_motions,
            scrape_leyes=run_leyes,
            scrape_others=run_others,
            only_current=args.only_current,
            scrape_documents=run_documents,
            upload_s3=args.upload_s3,
            leg_period=args.leg_period,
        )

    if not args.skip_processing:
        orchestrator.run_processing(
            process_bills=run_bills,
            process_motions=run_motions,
            process_leyes=run_leyes,
            process_others=run_others,
            process_documents=args.process_documents,
            process_votes=run_votes,
            votes_limit=args.votes_limit,
            votes_max_pages=args.votes_max_pages,
            votes_model=args.votes_model,
            votes_max_cost_usd=args.votes_max_cost_usd,
            first_load=args.first_summary,
            leg_period=args.leg_period,
            skip_extraction=args.skip_vote_extraction,
        )
