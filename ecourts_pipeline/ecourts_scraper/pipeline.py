"""Command-line pipeline entry point."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from rich.console import Console
from rich.progress import Progress

from .classification import HeuristicOutcomeClassifier
from .config import PipelineConfig
from .judge_normalizer import build_normalizer, load_judge_roster
from .pdf_utils import extract_text
from .scraper import open_scraper
from .state_entities import StateEntityMatcher


console = Console()
logger = logging.getLogger(__name__)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape Indian eCourts judgments for judge transfer study")
    parser.add_argument("run", nargs="?", default="run", help="Pipeline command (only 'run' is supported)")
    parser.add_argument("--config", required=True, help="Path to pipeline configuration YAML file")
    parser.add_argument("--limit-judges", type=int, default=None, help="Limit number of judges for dry runs")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip PDF downloading/text extraction (metadata only)",
    )
    return parser


def run_pipeline(config_path: Path, limit_judges: Optional[int] = None, skip_download: bool = False) -> None:
    config = PipelineConfig.from_yaml(config_path)
    roster_df = load_judge_roster(config.judge_roster)
    normalizer = build_normalizer(roster_df, config.judge_roster)
    matcher = StateEntityMatcher.from_file(config.classification.state_entities_path)
    classifier = HeuristicOutcomeClassifier()

    storage = config.storage
    storage.workspace.mkdir(parents=True, exist_ok=True)
    storage.raw_html_dir.mkdir(parents=True, exist_ok=True)
    storage.pdf_dir.mkdir(parents=True, exist_ok=True)
    storage.text_dir.mkdir(parents=True, exist_ok=True)

    aggregated: List[Dict[str, object]] = []

    with open_scraper(config.scraper, storage, matcher) as scraper, Progress(console=console) as progress:
        judge_task = progress.add_task("Scraping judges", total=limit_judges or len(roster_df))
        for idx, row in roster_df.iterrows():
            if limit_judges is not None and idx >= limit_judges:
                break
            canonical_name = row["__canonical_name"]
            alias_set = normalizer.alias_map.get(canonical_name, []) if hasattr(normalizer, "alias_map") else []
            combined_queries = [canonical_name] + row["__aliases"] + list(alias_set)
            seen: set[str] = set()
            queries: List[str] = []
            for variant in combined_queries:
                if not variant:
                    continue
                variant = variant.strip()
                key = variant.lower()
                if key not in seen:
                    seen.add(key)
                    queries.append(variant)
            cases = scraper.scrape_judge(canonical_name, queries)
            for case in cases:
                if not case.case_title:
                    continue
                if not matcher.contains_state_party(case.case_title):
                    continue

                pdf_path = None
                text_content = None
                if not skip_download:
                    try:
                        pdf_path = scraper.download_pdf(case)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Failed to download PDF for %s: %s", case.case_title, exc)
                    if pdf_path and pdf_path.exists():
                        try:
                            text_content = extract_text(pdf_path)
                            text_destination = Path(storage.text_dir) / (pdf_path.stem + ".txt")
                            text_destination.write_text(text_content, encoding="utf-8")
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Failed to extract text for %s: %s", pdf_path, exc)

                if text_content:
                    classification = classifier.classify(text_content)
                else:
                    classification = classifier.classify(case.case_title)

                record = case.to_serialisable()
                record.update(
                    {
                        "state_party": bool(case.state_entities),
                        "state_entities": case.state_entities,
                        "pdf_path": str(pdf_path) if pdf_path else None,
                        "outcome_label": classification.label.value,
                        "outcome_confidence": classification.confidence,
                        "outcome_snippets": classification.supporting_snippets,
                    }
                )
                aggregated.append(record)
            progress.advance(judge_task)

    if not aggregated:
        console.print("[yellow]No state-involved cases found with current filters.[/yellow]")
        return

    df = pd.DataFrame(aggregated)
    metadata_path = storage.metadata_path
    if metadata_path.suffix == ".parquet":
        df.to_parquet(metadata_path, index=False)
    else:
        df.to_csv(metadata_path, index=False)
    console.print(f"[green]Saved case metadata to {metadata_path}[/green]")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.run != "run":
        raise SystemExit("Only the 'run' command is supported")
    run_pipeline(Path(args.config), limit_judges=args.limit_judges, skip_download=args.skip_download)


if __name__ == "__main__":
    main()

