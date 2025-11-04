"""Playwright-based scraper for the eCourts PDF search portal."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
from dateutil import parser as date_parser
from playwright.sync_api import Browser, Download, Page, Playwright, sync_playwright
from rich.console import Console

from .config import ScraperConfig, StorageConfig
from .state_entities import StateEntityMatcher


logger = logging.getLogger(__name__)


@dataclass
class CaseMetadata:
    judge_canonical_name: str
    judge_query: str
    row_index: int
    cnr: Optional[str] = None
    case_title: Optional[str] = None
    registration_date: Optional[pd.Timestamp] = None
    decision_date: Optional[pd.Timestamp] = None
    disposal_nature: Optional[str] = None
    court_name: Optional[str] = None
    state_entities: List[str] = field(default_factory=list)
    detail_url: Optional[str] = None
    pdf_url: Optional[str] = None
    raw_row_html: Optional[str] = None

    def to_serialisable(self) -> Dict[str, object]:
        payload = asdict(self)
        for key in ("registration_date", "decision_date"):
            if payload[key] is not None:
                payload[key] = payload[key].isoformat()
        return payload


class EcourtsScraper:
    """Automates judge searches and captures case metadata."""

    RESULTS_TABLE_SELECTOR = "table#example"
    JUDGE_FILTER_SELECTOR = "input[name='judge']"
    SUBMIT_BUTTON_SELECTOR = "button#search"  # Update if the form uses a different widget
    RESET_BUTTON_SELECTOR = "button#reset"

    def __init__(self, scraper_config: ScraperConfig, storage_config: StorageConfig, matcher: StateEntityMatcher):
        self.config = scraper_config
        self.storage = storage_config
        self.matcher = matcher
        self.console = Console()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    def __enter__(self) -> "EcourtsScraper":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.config.headless)
        context = self._browser.new_context(
            viewport={"width": self.config.viewport_width, "height": self.config.viewport_height}
        )
        self._page = context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._page:
            self._page.context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Playwright page not initialised; use as context manager")
        return self._page

    def ensure_directories(self) -> None:
        for path in [
            self.storage.workspace,
            self.storage.raw_html_dir,
            self.storage.pdf_dir,
            self.storage.text_dir,
        ]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def navigate(self) -> None:
        logger.info("Navigating to %s", self.config.base_url)
        self.page.goto(self.config.base_url, wait_until="domcontentloaded")
        self._prompt_for_captcha_if_present()

    def _prompt_for_captcha_if_present(self) -> None:
        self.console.print("[yellow]Solve the captcha in the browser if one is displayed.[/yellow]")
        input(self.config.captcha_prompt + "\n")

    def scrape_judge(self, canonical_name: str, queries: Iterable[str]) -> List[CaseMetadata]:
        results: List[CaseMetadata] = []
        for query in queries:
            try:
                results.extend(self._scrape_single_query(canonical_name, query))
                if self.config.max_cases_per_judge and len(results) >= self.config.max_cases_per_judge:
                    break
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to collect data for judge %s (query=%s)", canonical_name, query)
                self.console.print(f"[red]Error scraping {canonical_name} with query '{query}': {exc}[/red]")
        return results[: self.config.max_cases_per_judge or None]

    def _scrape_single_query(self, canonical_name: str, query: str) -> List[CaseMetadata]:
        self.console.print(f"[bold cyan]Searching for judge:[/] {canonical_name} (query: {query})")
        self._reset_search_form()
        self._enter_judge_name(query)
        html_snapshot = self.page.content()
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        raw_path = (
            Path(self.storage.raw_html_dir)
            / f"results_{canonical_name.replace(' ', '_')}_{timestamp}.html"
        )
        raw_path.write_text(html_snapshot, encoding="utf-8")
        table_rows = self._extract_table_rows()
        cases: List[CaseMetadata] = []
        for index, row in enumerate(table_rows):
            meta = self._row_to_metadata(canonical_name, query, index, row)
            cases.append(meta)
        return cases

    def _reset_search_form(self) -> None:
        try:
            reset_button = self.page.locator(self.RESET_BUTTON_SELECTOR)
            if reset_button.count() > 0:
                reset_button.click()
                self.page.wait_for_timeout(500)
        except Exception:  # noqa: BLE001 - best effort reset
            pass

    def _enter_judge_name(self, name: str) -> None:
        locator = self.page.locator(self.JUDGE_FILTER_SELECTOR)
        if locator.count() == 0:
            raise RuntimeError(
                "Could not locate judge filter input. Update JUDGE_FILTER_SELECTOR in scraper.py"
            )
        locator.fill("")
        locator.type(name, delay=50)
        submit = self.page.locator(self.SUBMIT_BUTTON_SELECTOR)
        if submit.count() == 0:
            locator.press("Enter")
        else:
            submit.click()
        self.page.wait_for_timeout(max(self.config.request_delay_secs * 1000, 1500))

    def _extract_table_rows(self) -> List[Dict[str, object]]:
        table_present = self.page.locator(self.RESULTS_TABLE_SELECTOR)
        if table_present.count() == 0:
            logger.warning("Results table not found after search")
            return []

        script = """
        () => {
            const table = document.querySelector('table#example');
            if (!table) { return []; }
            const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.innerText.trim());
            return Array.from(table.querySelectorAll('tbody tr')).map((row, idx) => {
                const cells = Array.from(row.querySelectorAll('td'));
                const payload = { index: idx, cells: {}, links: [] };
                cells.forEach((cell, cellIdx) => {
                    const header = headers[cellIdx] || `col_${cellIdx}`;
                    payload.cells[header] = cell.innerText.trim();
                    const anchors = Array.from(cell.querySelectorAll('a'));
                    payload.links.push(...anchors.map(a => ({ href: a.href, text: a.innerText.trim() })));
                });
                payload.outerHTML = row.outerHTML;
                return payload;
            });
        }
        """
        rows = self.page.evaluate(script)
        if not isinstance(rows, list):
            logger.error("Unexpected table extraction result: %s", rows)
            return []
        return rows

    def _row_to_metadata(
        self,
        canonical_name: str,
        query: str,
        row_index: int,
        row: Dict[str, object],
    ) -> CaseMetadata:
        cells = row.get("cells", {})
        cnr = self._pick_cell(cells, ["CNR Number", "CNR No", "CNR"])
        case_title = self._pick_cell(cells, ["Case Title", "Title", "Case Details"])
        registration_date = self._parse_date(self._pick_cell(cells, ["Reg. Date", "Registration Date"]))
        decision_date = self._parse_date(self._pick_cell(cells, ["Decision Date", "Disposal Date", "Order Date"]))
        disposal_nature = self._pick_cell(cells, ["Disposition", "Disposal Nature", "Status"])
        court_name = self._pick_cell(cells, ["Court Name", "Court", "Bench"])
        state_entities = self.matcher.match_entities(case_title or "") if case_title else []
        pdf_url = self._extract_pdf_url(row.get("links", []))

        return CaseMetadata(
            judge_canonical_name=canonical_name,
            judge_query=query,
            row_index=row_index,
            cnr=cnr,
            case_title=case_title,
            registration_date=registration_date,
            decision_date=decision_date,
            disposal_nature=disposal_nature,
            court_name=court_name,
            state_entities=state_entities,
            detail_url=None,
            pdf_url=pdf_url,
            raw_row_html=row.get("outerHTML"),
        )

    @staticmethod
    def _pick_cell(cells: Dict[str, str], keys: List[str]) -> Optional[str]:
        for key in keys:
            if key in cells and cells[key]:
                return cells[key]
        # fallback to case-insensitive match
        lower_map = {k.lower(): v for k, v in cells.items() if v}
        for key in keys:
            if key.lower() in lower_map:
                return lower_map[key.lower()]
        return None

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[pd.Timestamp]:
        if not value or value in {"NA", "N/A", "-"}:
            return None
        try:
            parsed = date_parser.parse(value, dayfirst=True, fuzzy=True)
            return pd.Timestamp(parsed.date())
        except Exception:  # noqa: BLE001
            return None

    def _extract_pdf_url(self, links: List[Dict[str, str]]) -> Optional[str]:
        for link in links:
            href = link.get("href")
            if href and "pdf" in href.lower():
                return href
        return None

    def download_pdf(self, case: CaseMetadata) -> Optional[Path]:
        if not case.pdf_url:
            return None
        filename = f"{case.cnr or case.case_title or 'case'}_{case.row_index}.pdf"
        safe_name = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in filename)
        destination = Path(self.storage.pdf_dir) / safe_name

        with self.page.expect_download() as download_info:
            self.page.evaluate(
                "url => { window.open(url, '_blank'); }",
                case.pdf_url,
            )
        download: Download = download_info.value
        download.save_as(str(destination))
        download.delete()
        return destination


@contextmanager
def open_scraper(scraper_config: ScraperConfig, storage_config: StorageConfig, matcher: StateEntityMatcher):
    scraper = EcourtsScraper(scraper_config=scraper_config, storage_config=storage_config, matcher=matcher)
    scraper.ensure_directories()
    with scraper as ctx:
        ctx.navigate()
        yield ctx

