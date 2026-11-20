"""Evaluate visual category recognition with photos and independently supplied labels."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.vision.image_security import (  # noqa: E402
    ImageSecurityError,
    MAX_QC_IMAGE_BYTES,
    read_stored_image_bytes,
    validate_strip_exif_and_store,
)
from app.vision.provider import (  # noqa: E402
    VisionOutputValidationError,
    VisionProviderError,
    VisionProviderUnavailableError,
    resolve_vision_provider,
)
from app.vision.schemas import FoodCategoryEnum, ObservationStatusEnum, VisionAnalysisOutput  # noqa: E402

Label = Literal["visible", "not_visible", "uncertain"]


class EvaluationCase(BaseModel):
    id: str = Field(min_length=1)
    image: Path
    labels: dict[FoodCategoryEnum, Label] = Field(min_length=1)


class EvaluationManifest(BaseModel):
    cases: list[EvaluationCase] = Field(min_length=1)


def predicted_label(output: VisionAnalysisOutput, category: FoodCategoryEnum) -> Label:
    statuses = {
        component.observation_status for component in output.observed_components
        if component.category == category
    }
    if ObservationStatusEnum.VISIBLE in statuses:
        return "visible"
    if statuses & {ObservationStatusEnum.UNCERTAIN, ObservationStatusEnum.NEEDS_REVIEW}:
        return "uncertain"
    return "not_visible"


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def summarize(confusion: Counter[tuple[Label, Label]]) -> dict:
    labels = ("visible", "not_visible", "uncertain")
    matrix = {
        actual: {predicted: confusion[actual, predicted] for predicted in labels}
        for actual in labels
    }
    total = sum(confusion.values())
    true_positive = confusion["visible", "visible"]
    false_positive = confusion["not_visible", "visible"]
    missed_visible = confusion["visible", "not_visible"] + confusion["visible", "uncertain"]
    abstentions = confusion["visible", "uncertain"] + confusion["not_visible", "uncertain"]
    known = sum(matrix["visible"].values()) + sum(matrix["not_visible"].values())
    return {
        "labeled_components": total,
        "confusion_matrix": matrix,
        "exact_status_accuracy": _ratio(sum(confusion[label, label] for label in labels), total),
        "presence_precision": _ratio(true_positive, true_positive + false_positive),
        "presence_recall": _ratio(true_positive, true_positive + missed_visible),
        "presence_f1": _ratio(2 * true_positive, 2 * true_positive + false_positive + missed_visible),
        "decisive_coverage_on_known_labels": _ratio(known - abstentions, known),
    }


def run(manifest_path: Path, live: bool) -> tuple[dict, int]:
    manifest_path = manifest_path.resolve()
    manifest = EvaluationManifest.model_validate_json(manifest_path.read_text(encoding="utf-8-sig"))
    root = manifest_path.parent
    counts = Counter(f"{category.value}:{label}" for case in manifest.cases for category, label in case.labels.items())
    report = {"cases": len(manifest.cases), "label_counts": dict(sorted(counts.items()))}

    with TemporaryDirectory(prefix="gizioptima-vision-evaluation-") as temp_dir:
        # Evaluation must neither read nor write operational photo storage.
        previous_dir = os.environ.get("GIZIOPTIMA_QC_STORAGE_DIR")
        os.environ["GIZIOPTIMA_QC_STORAGE_DIR"] = temp_dir
        try:
            prepared = []
            seen_ids = set()
            seen_images = set()
            for case in manifest.cases:
                path = (root / case.image).resolve()
                if case.image.is_absolute() or not path.is_relative_to(root):
                    raise ValueError(f"Image path must stay within the manifest directory for {case.id}.")
                if case.id in seen_ids or path in seen_images:
                    raise ValueError(f"Duplicate case ID or image for {case.id}.")
                with path.open("rb") as stream:
                    image = validate_strip_exif_and_store(stream.read(MAX_QC_IMAGE_BYTES + 1), path.name)
                prepared.append((case, image))
                seen_ids.add(case.id)
                seen_images.add(path)
            if not live:
                return {**report, "status": "validated_only", "performed_live_requests": False}, 0

            provider = resolve_vision_provider()
            if not provider.is_live_ai:
                raise VisionProviderUnavailableError("Evaluasi akurasi memerlukan penyedia Vision AI live.")
            report.update(provider=provider.provider_name, model=provider.model_identifier)
            confusion: dict[FoodCategoryEnum, Counter[tuple[Label, Label]]] = {
                category: Counter() for category in FoodCategoryEnum
            }
            case_results = []
            failures = []
            for case, image in prepared:
                try:
                    result = provider.analyze_food_tray(
                        image_bytes=read_stored_image_bytes(image.storage_key),
                        mime_type=image.mime_type,
                        expected_menu=[],
                    )
                except (VisionProviderError, VisionOutputValidationError) as exc:
                    failures.append({"id": case.id, "error": str(exc)})
                    continue
                predictions = {}
                for category, actual in case.labels.items():
                    predicted = predicted_label(result.validated_output, category)
                    confusion[category][actual, predicted] += 1
                    predictions[category.value] = predicted
                case_results.append({"id": case.id, "predictions": predictions, "latency_ms": result.latency_ms})

            overall = Counter()
            for category_matrix in confusion.values():
                overall.update(category_matrix)
            return {
                **report,
                "status": "incomplete" if failures else "evaluated",
                "performed_live_requests": True,
                "successful_cases": len(case_results),
                "failed_cases": failures,
                "metrics": {
                    "overall": summarize(overall),
                    "per_category": {key.value: summarize(value) for key, value in confusion.items()},
                } if case_results else None,
                "case_results": case_results,
            }, int(bool(failures))
        finally:
            if previous_dir is None:
                os.environ.pop("GIZIOPTIMA_QC_STORAGE_DIR", None)
            else:
                os.environ["GIZIOPTIMA_QC_STORAGE_DIR"] = previous_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--live", action="store_true", help="Send the prepared images to the configured live provider.")
    args = parser.parse_args()
    try:
        report, code = run(args.manifest, args.live)
    except VisionProviderUnavailableError as exc:
        report, code = {"status": "configuration_required", "detail": str(exc), "performed_live_requests": False}, 2
    except (OSError, ValidationError, ImageSecurityError, ValueError) as exc:
        report, code = {"status": "invalid_input", "detail": str(exc)}, 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
