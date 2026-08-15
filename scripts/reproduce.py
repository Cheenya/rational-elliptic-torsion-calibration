from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
from pathlib import Path
import random
import sys
import tempfile
import time

from sage.all import EllipticCurve, QQ

from rational_torsion import compute_torsion, sage_reference
from rational_torsion.group import exact_order, subgroup_generated_by


CASE_HEADER = [
    "case_id",
    "case_kind",
    "expected_type",
    "a",
    "b",
    "provenance",
]
RESULT_HEADER = [
    "record_type",
    "metric",
    "value",
    "torsion_type",
    "case_id",
    "case_kind",
    "expected_type",
    "a",
    "b",
    "ours_type",
    "ours_order",
    "sage_type",
    "sage_order",
    "match",
    "detail",
]
SUMMARY_METRICS = [
    "status",
    "seed",
    "a_min",
    "a_max",
    "b_min",
    "b_max",
    "zero_coefficient_policy",
    "curated_case_count",
    "random_case_count",
    "total_case_count",
    "unique_pair_count",
    "singular_inputs_in_cases",
    "random_draw_attempts",
    "singular_redraw_count",
    "curated_overlap_redraw_count",
    "duplicate_random_redraw_count",
    "total_redraw_count",
    "random_a_zero_count",
    "random_b_zero_count",
    "random_any_zero_count",
    "match_count",
    "mismatch_count",
    "all_15_mazur_types_covered",
    "cases_sha256",
    "random_pairs_sha256",
    "outcomes_sha256",
    "max_seconds",
]
DETAIL_CODES = [
    "model_echo",
    "discriminant",
    "points_unique",
    "identity",
    "point_curve",
    "reference_generator_curve",
    "generator_membership",
    "generator_order",
    "generated_subgroup",
    "expected_type",
    "torsion_type",
    "torsion_order",
]
MAZUR_HEADER = ["expected_type", "a", "b", "provenance"]
MAZUR_TYPES = [
    "Z/1",
    "Z/2",
    "Z/2 x Z/2",
    "Z/3",
    "Z/4",
    "Z/5",
    "Z/6",
    "Z/7",
    "Z/8",
    "Z/9",
    "Z/10",
    "Z/12",
    "Z/2 x Z/4",
    "Z/2 x Z/6",
    "Z/2 x Z/8",
]
TYPE_ORDERS = {
    "Z/1": 1,
    "Z/2": 2,
    "Z/2 x Z/2": 4,
    "Z/3": 3,
    "Z/4": 4,
    "Z/5": 5,
    "Z/6": 6,
    "Z/7": 7,
    "Z/8": 8,
    "Z/9": 9,
    "Z/10": 10,
    "Z/12": 12,
    "Z/2 x Z/4": 8,
    "Z/2 x Z/6": 12,
    "Z/2 x Z/8": 16,
}
EXPECTED_GENERATOR_COUNTS = {
    "Z/1": 0,
    "Z/2": 1,
    "Z/2 x Z/2": 2,
    "Z/3": 1,
    "Z/4": 1,
    "Z/5": 1,
    "Z/6": 1,
    "Z/7": 1,
    "Z/8": 1,
    "Z/9": 1,
    "Z/10": 1,
    "Z/12": 1,
    "Z/2 x Z/4": 2,
    "Z/2 x Z/6": 2,
    "Z/2 x Z/8": 2,
}
EXPECTED_GENERATOR_EXPONENTS = {
    "Z/1": 1,
    "Z/2": 2,
    "Z/2 x Z/2": 2,
    "Z/3": 3,
    "Z/4": 4,
    "Z/5": 5,
    "Z/6": 6,
    "Z/7": 7,
    "Z/8": 8,
    "Z/9": 9,
    "Z/10": 10,
    "Z/12": 12,
    "Z/2 x Z/4": 4,
    "Z/2 x Z/6": 6,
    "Z/2 x Z/8": 8,
}
MAZUR_FIXTURE_SHA256 = (
    "ffb84f85b8d6923b88e6771dc14be3a10fa1a9cfdcfd67f8cd0074ff7064112d"
)
DEFAULT_SEED = 20260220
A_MIN = -10000
A_MAX = 10000
B_MIN = -10000
B_MAX = 10000
CANONICAL_SAMPLE_SIZE = 10000
CANONICAL_MAX_SECONDS = 3600.0
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAZUR_PATH = REPOSITORY_ROOT / "data" / "mazur_representatives.csv"


def _canonical_integer(text: str, *, label: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"{label} is not an integer: {text!r}") from exc
    if str(value) != text:
        raise ValueError(f"{label} is not canonical: {text!r}")
    return value


def _read_csv_bytes(path: Path, *, label: str) -> tuple[bytes, list[list[str]]]:
    if not path.is_file():
        raise ValueError(f"{label} does not exist")
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"{label} is empty")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError(f"{label} must use LF line endings and end with LF")
    try:
        text = raw.decode("utf-8")
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"malformed {label}: {exc}") from exc
    return raw, parsed


def _load_mazur_fixture(path: Path) -> list[tuple[str, str, str, str]]:
    raw, parsed = _read_csv_bytes(path, label="Mazur fixture")
    if hashlib.sha256(raw).hexdigest() != MAZUR_FIXTURE_SHA256:
        raise ValueError("Mazur fixture SHA-256 does not match the reviewed fixture")
    if not parsed or parsed[0] != MAZUR_HEADER:
        raise ValueError("Mazur fixture header is not canonical")
    rows = [tuple(row) for row in parsed[1:]]
    if len(rows) != 15 or any(len(row) != 4 for row in rows):
        raise ValueError("Mazur fixture must contain exactly 15 four-field rows")
    if [row[0] for row in rows] != MAZUR_TYPES:
        raise ValueError("Mazur fixture types are incomplete or reordered")

    seen_pairs: set[tuple[int, int]] = set()
    for index, (expected_type, a_text, b_text, provenance) in enumerate(rows, 1):
        if not expected_type or not provenance:
            raise ValueError(f"Mazur row {index} has an empty required field")
        a = _canonical_integer(a_text, label=f"Mazur row {index} coefficient a")
        b = _canonical_integer(b_text, label=f"Mazur row {index} coefficient b")
        pair = (a, b)
        if pair in seen_pairs:
            raise ValueError(f"Mazur row {index} duplicates coefficient pair {pair}")
        seen_pairs.add(pair)
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            raise ValueError(f"Mazur row {index} is singular")
    return rows


def _validate_sampling_parameters(*, seed: int, sample_size: int) -> None:
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(sample_size) is not int or not (0 < sample_size <= CANONICAL_SAMPLE_SIZE):
        raise ValueError("sample size must be in the range 1..10000")


def _build_case_rows(
    mazur_path: Path,
    *,
    seed: int,
    sample_size: int,
) -> tuple[list[tuple[str, ...]], dict[str, int]]:
    _validate_sampling_parameters(seed=seed, sample_size=sample_size)
    mazur_rows = _load_mazur_fixture(mazur_path)
    rows: list[tuple[str, ...]] = []
    curated_pairs: set[tuple[int, int]] = set()
    for index, (expected_type, a_text, b_text, provenance) in enumerate(
        mazur_rows,
        1,
    ):
        pair = (int(a_text, 10), int(b_text, 10))
        curated_pairs.add(pair)
        rows.append(
            (
                f"curated_{index:04d}",
                "curated",
                expected_type,
                a_text,
                b_text,
                provenance,
            )
        )

    generator = random.Random(seed)
    accepted_pairs: set[tuple[int, int]] = set()
    stats = {
        "random_draw_attempts": 0,
        "singular_redraw_count": 0,
        "curated_overlap_redraw_count": 0,
        "duplicate_random_redraw_count": 0,
        "random_a_zero_count": 0,
        "random_b_zero_count": 0,
        "random_any_zero_count": 0,
    }
    draw_cap = 100 * sample_size + 1000
    while len(accepted_pairs) < sample_size:
        if stats["random_draw_attempts"] >= draw_cap:
            raise RuntimeError(
                f"random draw cap exhausted after {draw_cap} attempts"
            )
        a = generator.randint(A_MIN, A_MAX)
        b = generator.randint(B_MIN, B_MAX)
        stats["random_draw_attempts"] += 1
        pair = (a, b)
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            stats["singular_redraw_count"] += 1
            continue
        if pair in curated_pairs:
            stats["curated_overlap_redraw_count"] += 1
            continue
        if pair in accepted_pairs:
            stats["duplicate_random_redraw_count"] += 1
            continue

        accepted_pairs.add(pair)
        if a == 0:
            stats["random_a_zero_count"] += 1
        if b == 0:
            stats["random_b_zero_count"] += 1
        if a == 0 or b == 0:
            stats["random_any_zero_count"] += 1
        rows.append(
            (
                f"random_{len(accepted_pairs):05d}",
                "random",
                "",
                str(a),
                str(b),
                f"random_seed_{seed}",
            )
        )
    return rows, stats


def _serialize_case_rows(rows: list[tuple[str, ...]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(CASE_HEADER)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _load_case_fixture(
    path: Path,
    mazur_path: Path,
    *,
    seed: int,
    sample_size: int,
) -> tuple[bytes, list[tuple[str, ...]], dict[str, int]]:
    raw, parsed = _read_csv_bytes(path, label="calibration case fixture")
    if not parsed or parsed[0] != CASE_HEADER:
        raise ValueError("calibration case fixture header is not canonical")
    rows = [tuple(row) for row in parsed[1:]]
    expected_rows, stats = _build_case_rows(
        mazur_path,
        seed=seed,
        sample_size=sample_size,
    )
    expected_count = 15 + sample_size
    if len(rows) != expected_count:
        raise ValueError(
            "calibration case fixture must contain "
            f"{expected_count} rows, found {len(rows)}"
        )
    if any(len(row) != len(CASE_HEADER) for row in rows):
        raise ValueError("calibration case rows must contain exactly six fields")

    seen_ids: set[str] = set()
    seen_pairs: set[tuple[int, int]] = set()
    for index, row in enumerate(rows, 1):
        case_id, case_kind, expected_type, a_text, b_text, provenance = row
        if case_id in seen_ids:
            raise ValueError(f"duplicate calibration case ID at row {index}")
        seen_ids.add(case_id)
        a = _canonical_integer(
            a_text,
            label=f"calibration row {index} coefficient a",
        )
        b = _canonical_integer(
            b_text,
            label=f"calibration row {index} coefficient b",
        )
        pair = (a, b)
        if pair in seen_pairs:
            raise ValueError(f"duplicate calibration pair at row {index}: {pair}")
        seen_pairs.add(pair)
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            raise ValueError(f"singular calibration pair at row {index}: {pair}")

        if index <= 15:
            if case_kind != "curated" or not expected_type or not provenance:
                raise ValueError(f"invalid curated calibration row {index}")
            if case_id != f"curated_{index:04d}":
                raise ValueError(f"invalid curated case ID at row {index}")
        else:
            random_index = index - 15
            if case_kind != "random" or expected_type:
                raise ValueError(f"invalid random calibration row {index}")
            if case_id != f"random_{random_index:05d}":
                raise ValueError(f"invalid random case ID at row {index}")
            if provenance != f"random_seed_{seed}":
                raise ValueError(f"invalid random provenance at row {index}")

    if rows != expected_rows:
        for index, (actual, expected) in enumerate(
            zip(rows, expected_rows, strict=True),
            1,
        ):
            if actual != expected:
                raise ValueError(
                    f"calibration row {index} differs from deterministic sequence"
                )
        raise ValueError("calibration fixture differs from deterministic sequence")
    return raw, rows, stats


def _monotonic() -> float:
    return time.monotonic()


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, ".15g")


def _result_row(
    *,
    record_type: str,
    metric: str = "",
    value: str = "",
    torsion_type: str = "",
    case_id: str = "",
    case_kind: str = "",
    expected_type: str = "",
    a: str = "",
    b: str = "",
    ours_type: str = "",
    ours_order: str = "",
    sage_type: str = "",
    sage_order: str = "",
    match: str = "",
    detail: str = "",
) -> list[str]:
    return [
        record_type,
        metric,
        value,
        torsion_type,
        case_id,
        case_kind,
        expected_type,
        a,
        b,
        ours_type,
        ours_order,
        sage_type,
        sage_order,
        match,
        detail,
    ]


def _evaluate_case(row: tuple[str, ...]) -> tuple[dict[str, str], str]:
    case_id, case_kind, expected_type, a_text, b_text, _provenance = row
    a = int(a_text, 10)
    b = int(b_text, 10)
    expected_discriminant = -16 * (4 * a**3 + 27 * b**2)
    curve = EllipticCurve(QQ, [a, b])
    identity = curve(0)

    try:
        ours = compute_torsion(a, b)
    except Exception as exc:
        raise RuntimeError(
            f"{case_id} ({a},{b}): own computation failed: {exc}"
        ) from exc
    try:
        reference = sage_reference(a, b)
    except Exception as exc:
        raise RuntimeError(
            f"{case_id} ({a},{b}): Sage reference failed: {exc}"
        ) from exc

    failures: set[str] = set()
    if ours.a != a or ours.b != b:
        failures.add("model_echo")
    if ours.discriminant != expected_discriminant:
        failures.add("discriminant")

    own_points = list(ours.torsion_points)
    distinct_own_points: list = []
    for point in own_points:
        if point not in distinct_own_points:
            distinct_own_points.append(point)
    own_order = len(distinct_own_points)
    if len(own_points) != own_order:
        failures.add("points_unique")
    if identity not in distinct_own_points:
        failures.add("identity")
    try:
        if any(point.curve() != curve for point in own_points):
            failures.add("point_curve")
    except Exception:
        failures.add("point_curve")
    try:
        if any(generator.curve() != curve for generator in reference.generators):
            failures.add("reference_generator_curve")
    except Exception:
        failures.add("reference_generator_curve")
    try:
        if any(generator not in distinct_own_points for generator in ours.generators):
            failures.add("generator_membership")
    except Exception:
        failures.add("generator_membership")

    generator_orders: list[int] = []
    for generator in ours.generators:
        try:
            order = exact_order(generator)
            if order is None:
                failures.add("generator_order")
            else:
                generator_orders.append(int(order))
        except Exception:
            failures.add("generator_order")
    expected_generator_count = EXPECTED_GENERATOR_COUNTS.get(ours.torsion_type)
    expected_generator_exponent = EXPECTED_GENERATOR_EXPONENTS.get(
        ours.torsion_type
    )
    if (
        expected_generator_count is None
        or expected_generator_exponent is None
        or len(ours.generators) != expected_generator_count
        or len(generator_orders) != len(ours.generators)
        or math.lcm(*generator_orders) != expected_generator_exponent
    ):
        failures.add("generator_order")
    try:
        generated_points = list(subgroup_generated_by(curve, ours.generators))
        if set(generated_points) != set(distinct_own_points):
            failures.add("generated_subgroup")
    except Exception:
        failures.add("generated_subgroup")

    if expected_type and (
        ours.torsion_type != expected_type
        or reference.torsion_type != expected_type
    ):
        failures.add("expected_type")
    own_type_order = TYPE_ORDERS.get(ours.torsion_type)
    reference_type_order = TYPE_ORDERS.get(reference.torsion_type)
    if (
        own_type_order is None
        or reference_type_order is None
        or ours.torsion_type != reference.torsion_type
    ):
        failures.add("torsion_type")
    if (
        own_order != reference.order
        or own_type_order != own_order
        or reference_type_order != reference.order
    ):
        failures.add("torsion_order")

    detail = ";".join(code for code in DETAIL_CODES if code in failures)
    match = "0" if detail else "1"
    outcome = {
        "case_id": case_id,
        "case_kind": case_kind,
        "expected_type": expected_type,
        "a": a_text,
        "b": b_text,
        "ours_type": str(ours.torsion_type),
        "ours_order": str(own_order),
        "sage_type": str(reference.torsion_type),
        "sage_order": str(reference.order),
        "match": match,
        "detail": detail,
    }
    payload = (
        f"{case_id},{a_text},{b_text},{expected_type},"
        f"{outcome['ours_type']},{outcome['ours_order']},"
        f"{outcome['sage_type']},{outcome['sage_order']},{match},{detail}\n"
    )
    return outcome, payload


def _run_calibration(
    rows: list[tuple[str, ...]],
    stats: dict[str, int],
    raw_cases: bytes,
    *,
    seed: int,
    sample_size: int,
    max_seconds: float,
) -> tuple[list[list[str]], int, int, int]:
    start = _monotonic()
    outcomes: list[dict[str, str]] = []
    outcome_payloads: list[str] = []
    type_counts = {torsion_type: 0 for torsion_type in MAZUR_TYPES}
    covered_types: set[str] = set()

    for processed, row in enumerate(rows):
        if _monotonic() - start > max_seconds:
            raise TimeoutError(
                f"cooperative timeout after processed {processed} cases"
            )
        outcome, payload = _evaluate_case(row)
        outcomes.append(outcome)
        outcome_payloads.append(payload)
        sage_type = outcome["sage_type"]
        if sage_type in type_counts:
            type_counts[sage_type] += 1
        if outcome["match"] == "1" and sage_type in type_counts:
            covered_types.add(sage_type)
        if _monotonic() - start > max_seconds:
            raise TimeoutError(
                f"cooperative timeout after processed {processed + 1} cases"
            )

    mismatch_outcomes = [outcome for outcome in outcomes if outcome["match"] == "0"]
    mismatch_count = len(mismatch_outcomes)
    match_count = len(outcomes) - mismatch_count
    coverage_count = len(covered_types)
    pairs = [(int(row[3], 10), int(row[4], 10)) for row in rows]
    random_rows = [row for row in rows if row[1] == "random"]
    random_pairs_payload = "".join(
        f"{row[3]},{row[4]}\n" for row in random_rows
    ).encode("utf-8")
    outcomes_payload = "".join(outcome_payloads).encode("utf-8")
    total_redraw_count = (
        stats["singular_redraw_count"]
        + stats["curated_overlap_redraw_count"]
        + stats["duplicate_random_redraw_count"]
    )
    release_pass = (
        seed == DEFAULT_SEED
        and sample_size == CANONICAL_SAMPLE_SIZE
        and max_seconds == CANONICAL_MAX_SECONDS
        and mismatch_count == 0
        and match_count == len(rows)
        and coverage_count == len(MAZUR_TYPES)
        and sum(type_counts.values()) == len(rows)
        and len(rows) == 15 + CANONICAL_SAMPLE_SIZE
        and len(set(pairs)) == len(rows)
        and all(-16 * (4 * a**3 + 27 * b**2) != 0 for a, b in pairs)
    )
    values = {
        "status": "pass" if release_pass else "fail",
        "seed": str(seed),
        "a_min": str(A_MIN),
        "a_max": str(A_MAX),
        "b_min": str(B_MIN),
        "b_max": str(B_MAX),
        "zero_coefficient_policy": "allowed_if_nonsingular",
        "curated_case_count": "15",
        "random_case_count": str(sample_size),
        "total_case_count": str(len(rows)),
        "unique_pair_count": str(len(set(pairs))),
        "singular_inputs_in_cases": str(
            sum(-16 * (4 * a**3 + 27 * b**2) == 0 for a, b in pairs)
        ),
        "random_draw_attempts": str(stats["random_draw_attempts"]),
        "singular_redraw_count": str(stats["singular_redraw_count"]),
        "curated_overlap_redraw_count": str(
            stats["curated_overlap_redraw_count"]
        ),
        "duplicate_random_redraw_count": str(
            stats["duplicate_random_redraw_count"]
        ),
        "total_redraw_count": str(total_redraw_count),
        "random_a_zero_count": str(stats["random_a_zero_count"]),
        "random_b_zero_count": str(stats["random_b_zero_count"]),
        "random_any_zero_count": str(stats["random_any_zero_count"]),
        "match_count": str(match_count),
        "mismatch_count": str(mismatch_count),
        "all_15_mazur_types_covered": "1" if coverage_count == 15 else "0",
        "cases_sha256": hashlib.sha256(raw_cases).hexdigest(),
        "random_pairs_sha256": hashlib.sha256(random_pairs_payload).hexdigest(),
        "outcomes_sha256": hashlib.sha256(outcomes_payload).hexdigest(),
        "max_seconds": _format_number(max_seconds),
    }
    result_rows = [
        _result_row(record_type="summary", metric=metric, value=values[metric])
        for metric in SUMMARY_METRICS
    ]
    result_rows.extend(
        _result_row(
            record_type="type_count",
            value=str(type_counts[torsion_type]),
            torsion_type=torsion_type,
        )
        for torsion_type in MAZUR_TYPES
    )
    result_rows.extend(
        _result_row(record_type="mismatch", **outcome)
        for outcome in mismatch_outcomes
    )
    return result_rows, match_count, mismatch_count, coverage_count


def _serialize_result_rows(rows: list[list[str]]) -> bytes:
    if any(len(row) != len(RESULT_HEADER) for row in rows):
        raise ValueError("calibration result row has an invalid field count")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(RESULT_HEADER)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _publish_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reproduce deterministic rational torsion calibration"
    )
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--sample-size", required=True, type=int)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-seconds", type=float, default=3600.0)
    parser.add_argument("--generate-cases", action="store_true")
    return parser


def main(argv=None) -> int:
    arguments = _argument_parser().parse_args(argv)
    try:
        _validate_sampling_parameters(
            seed=arguments.seed,
            sample_size=arguments.sample_size,
        )
        if arguments.generate_cases:
            if arguments.output is not None:
                raise ValueError("--output is not allowed with --generate-cases")
            rows, _stats = _build_case_rows(
                DEFAULT_MAZUR_PATH,
                seed=arguments.seed,
                sample_size=arguments.sample_size,
            )
            _publish_bytes_atomic(arguments.cases, _serialize_case_rows(rows))
        else:
            if arguments.output is None:
                raise ValueError("--output is required without --generate-cases")
            if not math.isfinite(arguments.max_seconds) or arguments.max_seconds <= 0:
                raise ValueError("max seconds must be finite and greater than zero")
            raw_cases, rows, stats = _load_case_fixture(
                arguments.cases,
                DEFAULT_MAZUR_PATH,
                seed=arguments.seed,
                sample_size=arguments.sample_size,
            )
            result_rows, match_count, mismatch_count, coverage_count = (
                _run_calibration(
                    rows,
                    stats,
                    raw_cases,
                    seed=arguments.seed,
                    sample_size=arguments.sample_size,
                    max_seconds=arguments.max_seconds,
                )
            )
            _publish_bytes_atomic(
                arguments.output,
                _serialize_result_rows(result_rows),
            )
    except Exception as exc:
        print(f"Calibration error: {exc}", file=sys.stderr)
        return 1

    if arguments.generate_cases:
        print(
            f"Calibration cases: 15 curated + {arguments.sample_size} random"
        )
        return 0
    print(
        f"Calibration: {match_count}/{15 + arguments.sample_size} matches, "
        f"{mismatch_count} mismatches"
    )
    print(f"Mazur coverage: {coverage_count}/15 types")
    return 2 if mismatch_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
