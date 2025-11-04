"""Configuration models for the eCourts scraping pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field, validator


class JudgeRosterConfig(BaseModel):
    """Options for reading and normalising the judge roster spreadsheet."""

    path: Path = Field(..., description="Path to the Excel/CSV file containing judge metadata")
    sheet_name: Optional[str] = Field(
        None, description="Sheet name (for Excel) that holds the judge list; defaults to first sheet"
    )
    name_column: str = Field(
        "JudgeName",
        description="Column containing judge names to query on the eCourts portal",
    )
    additional_alias_columns: List[str] = Field(
        default_factory=list,
        description="Optional columns that hold alternative spellings/aliases",
    )
    alias_lookup_path: Optional[Path] = Field(
        None,
        description="Optional CSV/JSON file that maps canonical names to additional aliases",
    )


class ScraperConfig(BaseModel):
    """Runtime options for the Playwright scraper."""

    base_url: str = Field("https://judgments.ecourts.gov.in/pdfsearch/index.php")
    headless: bool = Field(False, description="Run browser in headless mode")
    max_cases_per_judge: Optional[int] = Field(
        None, description="Limit the number of case rows to collect per judge"
    )
    request_delay_secs: float = Field(
        1.5,
        ge=0,
        description="Delay between successive row expansions/downloads to respect rate limits",
    )
    viewport_width: int = Field(1440)
    viewport_height: int = Field(900)
    captcha_prompt: str = Field(
        "Please solve the captcha displayed in the open browser window and press ENTER here.",
        description="Message shown to the operator when manual captcha input is required",
    )
    case_detail_pdf_selector: str = Field(
        "a[href*='getPDF']",
        description="CSS selector that targets the PDF download link in the case detail view",
    )


class StorageConfig(BaseModel):
    """Filesystem layout for captured artefacts."""

    workspace: Path = Field(..., description="Root directory for scraped artefacts")
    metadata_path: Path = Field(..., description="Location to write aggregated case metadata (parquet/csv)")
    raw_html_dir: Path = Field(..., description="Directory to persist raw HTML snapshots")
    pdf_dir: Path = Field(..., description="Directory for downloaded PDFs")
    text_dir: Path = Field(..., description="Directory for parsed PDF -> text artefacts")

    @validator("workspace", "metadata_path", "raw_html_dir", "pdf_dir", "text_dir")
    def resolve_paths(cls, value: Path) -> Path:
        return value.expanduser().resolve()


class ClassificationConfig(BaseModel):
    """Settings for state-entity detection and outcome classification."""

    state_entities_path: Path = Field(
        ..., description="CSV/TOML/YAML/JSON file listing state-related parties and aliases"
    )
    training_data_path: Optional[Path] = Field(
        None, description="Optional labelled dataset for supervised outcome classification"
    )
    model_output_path: Optional[Path] = Field(
        None, description="Where to persist trained classification models/weights"
    )


class PipelineConfig(BaseModel):
    """Top-level configuration for the scraping + analysis pipeline."""

    judge_roster: JudgeRosterConfig
    scraper: ScraperConfig
    storage: StorageConfig
    classification: ClassificationConfig

    @classmethod
    def from_yaml(cls, path: Path | str) -> "PipelineConfig":
        """Load configuration from a YAML file."""

        path = Path(path)
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        return cls.parse_obj(data)

