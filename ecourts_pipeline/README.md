## Overview

This package provides an end-to-end workflow for collecting, parsing, and analysing Indian High Court judgments from the eCourts portal. It focuses on identifying cases where the State (or related public entities) is a party and classifying outcomes that are favourable or unfavourable to the State. The primary research question is to study whether anti-State decisions increase the probability that a judge is strategically transferred in a manner that lowers their seniority.

Key capabilities:

- Normalise judge names from roster spreadsheets using fuzzy matching and curated aliases
- Automate eCourts searches with Playwright and capture case metadata
- Detect cases that involve government parties via a configurable entity dictionary
- Download and parse order/judgment PDFs with failover to OCR when required
- Extract ruling outcomes using both rule-based heuristics and machine-learning classifiers
- Persist the resulting dataset in SQLite or Parquet for downstream modelling (event studies, survival models, etc.)

The scraping component requires manual CAPTCHA entry (or an approved CAPTCHA-solving service) for compliance with the eCourts terms of use.

## Installation

```bash
cd /workspace/ecourts_pipeline
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
playwright install chromium
```

## Quick Start

Create a configuration file (for example `config.example.yml`) specifying judge roster, output folders, and runtime options. Then run:

```bash
python -m ecourts_scraper.pipeline run --config config.example.yml
```

The CLI will prompt for CAPTCHA solutions during scraping. Outputs (raw HTML, case metadata, PDFs, parsed text, analytic tables) are stored under the configured working directory.

Refer to inline docstrings and comments for details on extending the classification logic or integrating the resulting dataset into statistical analyses of judicial transfers.
