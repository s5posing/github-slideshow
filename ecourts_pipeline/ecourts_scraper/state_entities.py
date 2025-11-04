"""Detect whether case titles involve the State or related entities."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

import yaml


def _normalise(text: str) -> str:
    return " ".join(text.lower().replace("&", "and").split())


def load_entities(path: Path) -> List[str]:
    path = path.expanduser().resolve()
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        data = yaml.safe_load(path.read_text())
        if isinstance(data, dict):
            entities = []
            for values in data.values():
                if isinstance(values, str):
                    entities.append(values)
                elif isinstance(values, Iterable):
                    entities.extend(str(v) for v in values)
        else:
            entities = [str(item) for item in data]
        return entities
    if suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            entities = []
            for value in data.values():
                if isinstance(value, str):
                    entities.append(value)
                elif isinstance(value, Iterable):
                    entities.extend(str(v) for v in value)
        else:
            entities = [str(item) for item in data]
        return entities
    if suffix in {".csv", ".tsv"}:
        delimiter = "," if suffix == ".csv" else "\t"
        entities: List[str] = []
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if "entity" not in reader.fieldnames:
                raise ValueError("CSV/TSV entity lists must contain an 'entity' column")
            for row in reader:
                entity = row.get("entity")
                if entity:
                    entities.append(entity)
        return entities
    raise ValueError(f"Unsupported entity list format: {suffix}")


@dataclass
class StateEntityMatcher:
    canonical_entities: Set[str]
    minimum_token_length: int = 3

    @classmethod
    def from_file(cls, path: Path) -> "StateEntityMatcher":
        entities = {_normalise(name) for name in load_entities(path)}
        return cls(canonical_entities=entities)

    def _tokenise(self, text: str) -> List[str]:
        return [token for token in _normalise(text).split() if len(token) >= self.minimum_token_length]

    def contains_state_party(self, case_title: str) -> bool:
        tokens = self._tokenise(case_title)
        joined = " ".join(tokens)
        for entity in self.canonical_entities:
            if entity in joined:
                return True
        return False

    def match_entities(self, case_title: str) -> List[str]:
        tokens = self._tokenise(case_title)
        joined = " ".join(tokens)
        return [entity for entity in self.canonical_entities if entity in joined]

