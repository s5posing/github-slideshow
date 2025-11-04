"""Outcome classification utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class OutcomeLabel(str, Enum):
    PRO_STATE = "pro_state"
    ANTI_STATE = "anti_state"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    label: OutcomeLabel
    confidence: float
    supporting_snippets: List[str]


class HeuristicOutcomeClassifier:
    """Simple rule-based classifier driven by regex heuristics."""

    PRO_PATTERNS = [
        r"petition\s+dismissed",
        r"writ\s+petition\s+dismissed",
        r"appeal\s+dismissed",
        r"relief\s+denied",
        r"in\s+favour\s+of\s+the\s+state",
    ]
    ANTI_PATTERNS = [
        r"petition\s+allowed",
        r"writ\s+petition\s+allowed",
        r"relief\s+granted",
        r"set\s+aside\s+the\s+order\s+of\s+the\s+state",
        r"against\s+the\s+state",
    ]

    def __init__(self, extra_patterns: Optional[Dict[str, List[str]]] = None):
        if extra_patterns:
            self.PRO_PATTERNS.extend(extra_patterns.get("pro_state", []))
            self.ANTI_PATTERNS.extend(extra_patterns.get("anti_state", []))
        self._compiled_pro = [re.compile(pattern, re.IGNORECASE) for pattern in self.PRO_PATTERNS]
        self._compiled_anti = [re.compile(pattern, re.IGNORECASE) for pattern in self.ANTI_PATTERNS]

    def classify(self, text: str) -> ClassificationResult:
        pro_hits = self._match_patterns(self._compiled_pro, text)
        anti_hits = self._match_patterns(self._compiled_anti, text)

        if pro_hits and not anti_hits:
            return ClassificationResult(OutcomeLabel.PRO_STATE, confidence=0.6, supporting_snippets=pro_hits)
        if anti_hits and not pro_hits:
            return ClassificationResult(OutcomeLabel.ANTI_STATE, confidence=0.6, supporting_snippets=anti_hits)
        if pro_hits and anti_hits:
            return ClassificationResult(
                OutcomeLabel.MIXED,
                confidence=0.4,
                supporting_snippets=pro_hits + anti_hits,
            )
        return ClassificationResult(OutcomeLabel.UNKNOWN, confidence=0.2, supporting_snippets=[])

    @staticmethod
    def _match_patterns(patterns, text: str) -> List[str]:
        snippets: List[str] = []
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                snippet_start = max(match.start() - 40, 0)
                snippet_end = min(match.end() + 40, len(text))
                snippets.append(text[snippet_start:snippet_end])
        return snippets

