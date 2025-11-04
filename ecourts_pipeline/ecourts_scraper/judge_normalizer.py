"""Utilities to standardise judge names from roster spreadsheets."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd
from thefuzz import fuzz, process

from .config import JudgeRosterConfig


HONORIFICS = [
    "justice",
    "hon'ble",
    "hon",
    "mr",
    "mrs",
    "ms",
    "shri",
    "smt",
    "dr",
]


def _simplify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z\s]", " ", name)
    name = re.sub(r"\s+", " ", name)
    tokens = [token for token in name.split() if token and token not in HONORIFICS]
    return " ".join(tokens)


class NameNormalizer:
    """Provides fuzzy matching between raw judge names and canonical identifiers."""

    def __init__(self, canonical_names: Sequence[str], alias_map: Optional[Dict[str, List[str]]] = None):
        self.canonical_names = sorted({name.strip(): None for name in canonical_names}.keys())
        self.alias_map = alias_map or {}
        self.lookup_index = self._build_index(self.canonical_names, self.alias_map)

    @staticmethod
    def _build_index(names: Sequence[str], alias_map: Dict[str, List[str]]) -> Dict[str, str]:
        index = {}
        for canonical in names:
            simplified = _simplify(canonical)
            if simplified:
                index[simplified] = canonical
            for alias in alias_map.get(canonical, []):
                simplified_alias = _simplify(alias)
                if simplified_alias:
                    index[simplified_alias] = canonical
        return index

    def match(self, query: str, score_cutoff: int = 83) -> Optional[str]:
        """Return the best canonical name for the provided query."""

        simplified_query = _simplify(query)
        if not simplified_query:
            return None

        if simplified_query in self.lookup_index:
            return self.lookup_index[simplified_query]

        candidates = list(self.lookup_index.keys())
        best = process.extractOne(simplified_query, candidates, scorer=fuzz.token_set_ratio)
        if best and best[1] >= score_cutoff:
            return self.lookup_index[best[0]]
        return None


def load_alias_map(path: Optional[Path]) -> Dict[str, List[str]]:
    if not path:
        return {}

    path = path.expanduser().resolve()
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
    if path.suffix.lower() in {".csv", ".tsv"}:
        df = pd.read_csv(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported alias file format: {path.suffix}")

    required_cols = {"canonical", "alias"}
    if not required_cols.issubset(df.columns.str.lower()):
        raise ValueError("Alias file must have 'canonical' and 'alias' columns (case-insensitive)")

    alias_dict: Dict[str, List[str]] = defaultdict(list)
    for _, row in df.iterrows():
        canonical = row.get("canonical") or row.get("Canonical") or row.get("CANONICAL")
        alias = row.get("alias") or row.get("Alias") or row.get("ALIAS")
        if pd.notna(canonical) and pd.notna(alias):
            alias_dict[str(canonical).strip()].append(str(alias).strip())
    return dict(alias_dict)


def load_judge_roster(config: JudgeRosterConfig) -> pd.DataFrame:
    path = config.path.expanduser().resolve()
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, sheet_name=config.sheet_name)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported roster file format: {path.suffix}")

    if config.name_column not in df.columns:
        raise KeyError(f"Name column '{config.name_column}' not found in roster")

    alias_columns = [col for col in config.additional_alias_columns if col in df.columns]
    df = df.copy()
    df["__canonical_name"] = (
        df[config.name_column].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    )
    df["__aliases"] = df.apply(
        lambda row: [
            str(row[col]).strip()
            for col in alias_columns
            if pd.notna(row[col]) and str(row[col]).strip()
        ],
        axis=1,
    )
    return df


def build_normalizer(df: pd.DataFrame, config: JudgeRosterConfig) -> NameNormalizer:
    canonical_names = df["__canonical_name"].tolist()
    alias_map = load_alias_map(config.alias_lookup_path)
    for _, row in df.iterrows():
        aliases = row["__aliases"]
        if aliases:
            alias_map.setdefault(row["__canonical_name"], []).extend(aliases)
    return NameNormalizer(canonical_names=canonical_names, alias_map=alias_map)


def iter_queries(df: pd.DataFrame) -> Iterable[Dict[str, str]]:
    for _, row in df.iterrows():
        yield {
            "canonical_name": row["__canonical_name"],
            "aliases": row["__aliases"],
        }

