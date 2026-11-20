from __future__ import annotations

import re
import unicodedata
from typing import List

from app.vision.schemas import (
    ComparisonStatusEnum,
    ExpectedMenuSlot,
    ExpectedVsObservedFinding,
    ObservationStatusEnum,
    VisionAnalysisOutput,
)

FINDING_LABELS = {
    ComparisonStatusEnum.VISUAL_MATCH: "Terlihat sesuai secara visual.",
    ComparisonStatusEnum.MISSING_EXPECTED: "Komponen yang diharapkan belum terlihat.",
    ComparisonStatusEnum.UNCERTAIN: "Komponen sulit diidentifikasi.",
    ComparisonStatusEnum.NEEDS_MANUAL_CHECK: "Perlu pemeriksaan manual.",
}


def _normalized_food_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"\w+", normalized))


def compare_expected_menu_with_observations(
    expected_menu: List[ExpectedMenuSlot],
    vision_output: VisionAnalysisOutput,
) -> List[ExpectedVsObservedFinding]:
    """Deterministically compare persisted planned menu slots against validated AI observations.

    Never claims nutritional completeness, exact ingredient weight, or microbiological safety.
    """
    findings: List[ExpectedVsObservedFinding] = []
    obs_by_cat = {}
    for comp in vision_output.observed_components:
        obs_by_cat.setdefault(comp.category.value, []).append(comp)

    for expected in expected_menu:
        candidates = obs_by_cat.get(expected.slot, [])
        if not candidates:
            findings.append(
                ExpectedVsObservedFinding(
                    slot=expected.slot,
                    expected_recipe_name=expected.recipe_name,
                    status=ComparisonStatusEnum.MISSING_EXPECTED,
                    finding_label=FINDING_LABELS[ComparisonStatusEnum.MISSING_EXPECTED],
                    matched_observation=None,
                    explanation=(
                        f"Rencana menu memuat '{expected.recipe_name}', namun tidak ada komponen "
                        f"kategori '{expected.slot}' yang terdeteksi jelas pada foto. Periksa sampel secara langsung."
                    ),
                )
            )
            continue

        visible_matches = [
            c for c in candidates if c.observation_status == ObservationStatusEnum.VISIBLE
        ]
        uncertain_matches = [
            c
            for c in candidates
            if c.observation_status
            in {ObservationStatusEnum.UNCERTAIN, ObservationStatusEnum.NEEDS_REVIEW}
        ]

        expected_name = _normalized_food_name(expected.recipe_name)
        same_name = next(
            (
                component for component in visible_matches
                if expected_name and _normalized_food_name(component.possible_food_name) == expected_name
            ),
            None,
        )
        if same_name:
            findings.append(
                ExpectedVsObservedFinding(
                    slot=expected.slot,
                    expected_recipe_name=expected.recipe_name,
                    status=ComparisonStatusEnum.VISUAL_MATCH,
                    finding_label=FINDING_LABELS[ComparisonStatusEnum.VISUAL_MATCH],
                    matched_observation=same_name.possible_food_name,
                    explanation=(
                        f"Terlihat '{same_name.possible_food_name}' untuk kategori {expected.slot} "
                        f"(rencana: '{expected.recipe_name}'). Konfirmasi manual tetap diperlukan untuk porsi & bahan tercampur."
                    ),
                )
            )
        elif visible_matches:
            findings.append(
                ExpectedVsObservedFinding(
                    slot=expected.slot,
                    expected_recipe_name=expected.recipe_name,
                    status=ComparisonStatusEnum.NEEDS_MANUAL_CHECK,
                    finding_label=FINDING_LABELS[ComparisonStatusEnum.NEEDS_MANUAL_CHECK],
                    matched_observation=visible_matches[0].possible_food_name,
                    explanation="Kategori terlihat, tetapi nama makanan belum dapat dicocokkan dengan rencana. Periksa sampel secara langsung.",
                )
            )
        elif uncertain_matches:
            best = uncertain_matches[0]
            findings.append(
                ExpectedVsObservedFinding(
                    slot=expected.slot,
                    expected_recipe_name=expected.recipe_name,
                    status=ComparisonStatusEnum.UNCERTAIN,
                    finding_label=FINDING_LABELS[ComparisonStatusEnum.UNCERTAIN],
                    matched_observation=best.possible_food_name,
                    explanation=(
                        f"Terdeteksi '{best.possible_food_name}' namun statusnya tidak pasti ({best.observation_status.value}). "
                        "Petugas QC perlu memeriksa langsung kecocokannya dengan rencana menu."
                    ),
                )
            )
        else:
            findings.append(
                ExpectedVsObservedFinding(
                    slot=expected.slot,
                    expected_recipe_name=expected.recipe_name,
                    status=ComparisonStatusEnum.MISSING_EXPECTED,
                    finding_label=FINDING_LABELS[ComparisonStatusEnum.MISSING_EXPECTED],
                    explanation="Komponen ditandai belum terlihat pada foto. Periksa sampel secara langsung.",
                )
            )

    return findings
