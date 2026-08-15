from __future__ import annotations

import argparse
import ast
import csv
import getpass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata

from sage.all import EllipticCurve, QQ
from sage.env import SAGE_VERSION

from rational_torsion import compute_torsion, sage_reference
from rational_torsion.group import exact_order, subgroup_generated_by


ROOT = Path(__file__).resolve().parents[1]
SEED = 20260220
A_MIN = -10000
A_MAX = 10000
B_MIN = -10000
B_MAX = 10000
CANONICAL_RANDOM_SIZE = 10000
CANONICAL_MAX_SECONDS = 3600
REVIEWED_SOURCE_SHA256 = {
    "__init__.py": "b56977c273a387ee2808bfb4235463a045251b6ea3cc9b16a85cd3a77640deb8",
    "candidates.py": "f839a8e6f096db2bc40f3e06e925d4d159fbf29697043a8c37ada1a07ace0f2a",
    "core.py": "aadd9d3dcc6d1e49c0e231c9fe969d79d8d9f11432d0c5b66dc0c7d293330a5d",
    "group.py": "4ecdf2d1b576c4b81ee3df89c8df9180418657c0253d03b9cc3ed9097deb9daa",
    "model.py": "b73db3df4114d56c41375518039178bab6dbf1981345392518277f3dec217121",
    "reference.py": "be91b67623a18e3db38a79ad49ba182120eba1e59cb89a512f5a4938b619fbee",
}

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
GENERATOR_COUNTS = {
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
GENERATOR_EXPONENTS = {
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
MAZUR_ROWS = [
    ["Z/1", "-10", "-10", "coefficient_grid"],
    ["Z/2", "-10", "-9", "coefficient_grid"],
    ["Z/2 x Z/2", "-9", "0", "coefficient_grid"],
    ["Z/3", "-9", "9", "coefficient_grid"],
    ["Z/4", "-2", "1", "coefficient_grid"],
    ["Z/5", "-432", "8208", "Adamova_reference"],
    ["Z/6", "0", "1", "coefficient_grid"],
    ["Z/7", "-43", "166", "Adamova_reference"],
    ["Z/8", "-44091", "3304854", "Adamova_reference"],
    ["Z/9", "-219", "1654", "calibration"],
    ["Z/10", "-58347", "3954150", "Cremona_66c1_short_model"],
    ["Z/12", "-1947", "108214", "calibration"],
    ["Z/2 x Z/4", "-12987", "-263466", "Cremona_15a1_short_model"],
    ["Z/2 x Z/6", "-24003", "1296702", "calibration"],
    ["Z/2 x Z/8", "-1386747", "368636886", "Cremona_210e2_short_model"],
]

MAZUR_FIXTURE_HEADER = ["expected_type", "a", "b", "provenance"]
MAZUR_RESULT_HEADER = [
    "expected_type",
    "expected_order",
    "a",
    "b",
    "provenance",
    "discriminant",
    "ours_type",
    "ours_order",
    "ours_point_count",
    "ours_generator_orders",
    "ours_generators",
    "sage_type",
    "sage_order",
    "sage_generators",
    "match",
]
GRID_FIXTURE_HEADER = ["curve_id", "a", "b"]
GRID_RESULT_HEADER = [
    "curve_id",
    "a",
    "b",
    "discriminant",
    "ours_type",
    "ours_order",
    "ours_generator_orders",
    "ours_generators",
    "sage_type",
    "sage_order",
    "sage_generators",
    "match",
]
CALIBRATION_CASE_HEADER = [
    "case_id",
    "case_kind",
    "expected_type",
    "a",
    "b",
    "provenance",
]
CALIBRATION_RESULT_HEADER = [
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
ENVIRONMENT_FIELDS = [
    "os",
    "architecture",
    "cpu_model",
    "logical_cores",
    "memory_gib",
    "sage_version",
    "python_version",
    "compiler_version",
]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_integer(value, *, label: str) -> int:
    if type(value) is not str:
        raise ValueError(f"{label} must be a string containing a canonical integer")
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise ValueError(f"{label} is not an integer: {value!r}") from exc
    if str(parsed) != value:
        raise ValueError(f"{label} is not canonical: {value!r}")
    return parsed


def _canonical_sha256(value, *, label: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} is not a lower-case SHA-256 value")
    return value


def _read_csv_exact(
    path: Path,
    *,
    label: str,
    header: list[str],
) -> tuple[bytes, list[list[str]]]:
    if not path.is_file():
        raise ValueError(f"{label} does not exist")
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"{label} is empty")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError(f"{label} must use LF endings and end with exactly one LF")
    try:
        text = raw.decode("utf-8")
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"{label} is malformed: {exc}") from exc
    if not parsed or parsed[0] != header:
        raise ValueError(f"{label} header is not canonical")
    rows = parsed[1:]
    for index, row in enumerate(rows, 1):
        if len(row) != len(header) or any(value is None for value in row):
            raise ValueError(
                f"{label} row {index} must contain exactly {len(header)} fields"
            )
    return raw, rows


def _serialize_csv(header: list[str], rows: list[list[str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _assert_rows_equal(
    actual: list[list[str]],
    expected: list[list[str]],
    *,
    label: str,
) -> None:
    if len(actual) != len(expected):
        raise ValueError(
            f"{label} row count differs: found {len(actual)}, expected {len(expected)}"
        )
    for index, (actual_row, expected_row) in enumerate(
        zip(actual, expected, strict=True),
        1,
    ):
        if actual_row != expected_row:
            differing = next(
                (
                    offset
                    for offset, (left, right) in enumerate(
                        zip(actual_row, expected_row, strict=True)
                    )
                    if left != right
                ),
                0,
            )
            raise ValueError(
                f"{label} row {index} field {differing + 1} differs from fresh semantics"
            )


def _serialize_rational(value) -> str:
    rational = QQ(value)
    if rational.denominator() == 1:
        return str(rational.numerator())
    return f"{rational.numerator()}/{rational.denominator()}"


def _serialize_point(point) -> str:
    if hasattr(point, "element"):
        point = point.element()
    if point.is_zero():
        return "O"
    return f"({_serialize_rational(point[0])},{_serialize_rational(point[1])})"


def _serialize_generators(generators) -> str:
    return ";".join(_serialize_point(point) for point in generators)


def _evaluate_pair(
    a: int,
    b: int,
    *,
    expected_type: str = "",
    compute_fn=None,
    reference_fn=None,
) -> dict[str, object]:
    expected_discriminant = -16 * (4 * a**3 + 27 * b**2)
    if expected_discriminant == 0:
        raise ValueError(f"singular pair ({a},{b})")
    curve = EllipticCurve(QQ, [a, b])
    identity = curve(0)
    if compute_fn is None:
        compute_fn = compute_torsion
    if reference_fn is None:
        reference_fn = sage_reference
    try:
        ours = compute_fn(a, b)
    except Exception as exc:
        raise ValueError(f"own computation failed at ({a},{b}): {exc}") from exc
    try:
        reference = reference_fn(a, b)
    except Exception as exc:
        raise ValueError(f"Sage reference failed at ({a},{b}): {exc}") from exc

    if ours.a != a or ours.b != b:
        raise ValueError(f"model echo mismatch at ({a},{b})")
    if ours.discriminant != expected_discriminant:
        raise ValueError(f"discriminant mismatch at ({a},{b})")
    if ours.torsion_type not in TYPE_ORDERS:
        raise ValueError(f"unknown own torsion type at ({a},{b})")
    if reference.torsion_type not in TYPE_ORDERS:
        raise ValueError(f"unknown Sage torsion type at ({a},{b})")

    own_points = list(ours.torsion_points)
    distinct_points = set(own_points)
    if len(own_points) != len(distinct_points):
        raise ValueError(f"duplicate own point at ({a},{b})")
    if identity not in distinct_points:
        raise ValueError(f"identity is missing at ({a},{b})")
    try:
        if any(point.curve() != curve for point in own_points):
            raise ValueError(f"own point is off the input curve at ({a},{b})")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"own point curve check failed at ({a},{b})") from exc
    try:
        if any(generator.curve() != curve for generator in reference.generators):
            raise ValueError(f"Sage generator is off the input curve at ({a},{b})")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Sage generator curve check failed at ({a},{b})") from exc
    if any(generator not in distinct_points for generator in ours.generators):
        raise ValueError(f"own generator is outside the torsion set at ({a},{b})")

    generator_orders: list[int] = []
    for generator in ours.generators:
        order = exact_order(generator)
        if order is None:
            raise ValueError(f"nonfinite own generator order at ({a},{b})")
        generator_orders.append(int(order))
    if len(ours.generators) != GENERATOR_COUNTS[ours.torsion_type]:
        raise ValueError(f"own generator count mismatch at ({a},{b})")
    if math.lcm(*generator_orders) != GENERATOR_EXPONENTS[ours.torsion_type]:
        raise ValueError(f"own generator exponent mismatch at ({a},{b})")
    try:
        generated = set(subgroup_generated_by(curve, ours.generators))
    except Exception as exc:
        raise ValueError(f"own subgroup generation failed at ({a},{b})") from exc
    if generated != distinct_points:
        raise ValueError(f"own generators do not generate the torsion set at ({a},{b})")

    own_order = len(distinct_points)
    if TYPE_ORDERS[ours.torsion_type] != own_order:
        raise ValueError(f"own type and point count differ at ({a},{b})")
    if TYPE_ORDERS[reference.torsion_type] != reference.order:
        raise ValueError(f"Sage type and order differ at ({a},{b})")
    if ours.torsion_type != reference.torsion_type or own_order != reference.order:
        raise ValueError(f"own and Sage torsion structures differ at ({a},{b})")
    if expected_type and (
        ours.torsion_type != expected_type or reference.torsion_type != expected_type
    ):
        raise ValueError(f"expected torsion type differs at ({a},{b})")

    return {
        "discriminant": expected_discriminant,
        "ours_type": ours.torsion_type,
        "ours_order": own_order,
        "ours_generator_orders": generator_orders,
        "ours_generators": _serialize_generators(ours.generators),
        "sage_type": reference.torsion_type,
        "sage_order": int(reference.order),
        "sage_generators": _serialize_generators(reference.generators),
    }


def _load_mazur_fixture(path: Path) -> tuple[bytes, list[list[str]]]:
    raw, rows = _read_csv_exact(
        path,
        label="Mazur fixture",
        header=MAZUR_FIXTURE_HEADER,
    )
    if len(rows) != 15:
        raise ValueError(f"Mazur fixture must contain 15 rows, found {len(rows)}")
    for index, row in enumerate(rows, 1):
        _canonical_integer(row[1], label=f"Mazur fixture row {index} coefficient a")
        _canonical_integer(row[2], label=f"Mazur fixture row {index} coefficient b")
    _assert_rows_equal(rows, MAZUR_ROWS, label="Mazur fixture")
    pairs = {(int(row[1]), int(row[2])) for row in rows}
    if len({row[0] for row in rows}) != 15 or len(pairs) != 15:
        raise ValueError("Mazur fixture types and pairs must be unique")
    if any(-16 * (4 * a**3 + 27 * b**2) == 0 for a, b in pairs):
        raise ValueError("Mazur fixture contains a singular pair")
    return raw, rows


def _validate_mazur_result_scalars(rows: list[list[str]]) -> None:
    if len(rows) != 15:
        raise ValueError(f"Mazur result must contain 15 rows, found {len(rows)}")
    for index, row in enumerate(rows, 1):
        for column in (1, 2, 3, 5, 7, 8, 12, 14):
            _canonical_integer(
                row[column],
                label=f"Mazur result row {index} field {column + 1}",
            )
        if row[9]:
            for value in row[9].split(";"):
                parsed = _canonical_integer(
                    value,
                    label=f"Mazur result row {index} generator order",
                )
                if parsed < 1:
                    raise ValueError(f"Mazur result row {index} has an invalid order")
        if row[14] != "1":
            raise ValueError(f"Mazur result row {index} field match must be literal 1")


def _verify_mazur(fixture_path: Path, result_path: Path) -> list[list[str]]:
    _raw, fixture_rows = _load_mazur_fixture(fixture_path)
    _result_raw, result_rows = _read_csv_exact(
        result_path,
        label="Mazur result",
        header=MAZUR_RESULT_HEADER,
    )
    _validate_mazur_result_scalars(result_rows)
    expected_rows: list[list[str]] = []
    for expected_type, a_text, b_text, provenance in fixture_rows:
        a = int(a_text, 10)
        b = int(b_text, 10)
        semantics = _evaluate_pair(a, b, expected_type=expected_type)
        expected_rows.append(
            [
                expected_type,
                str(TYPE_ORDERS[expected_type]),
                a_text,
                b_text,
                provenance,
                str(semantics["discriminant"]),
                str(semantics["ours_type"]),
                str(semantics["ours_order"]),
                str(semantics["ours_order"]),
                ";".join(str(value) for value in semantics["ours_generator_orders"]),
                str(semantics["ours_generators"]),
                str(semantics["sage_type"]),
                str(semantics["sage_order"]),
                str(semantics["sage_generators"]),
                "1",
            ]
        )
    _assert_rows_equal(result_rows, expected_rows, label="Mazur result")
    return fixture_rows


def _canonical_grid_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for a in range(-10, 11):
        for b in range(-10, 11):
            if -16 * (4 * a**3 + 27 * b**2) != 0:
                rows.append([f"curve_{len(rows) + 1:04d}", str(a), str(b)])
    return rows


def _load_grid_fixture(path: Path) -> list[list[str]]:
    _raw, rows = _read_csv_exact(
        path,
        label="grid fixture",
        header=GRID_FIXTURE_HEADER,
    )
    if len(rows) != 438:
        raise ValueError(f"grid fixture must contain 438 rows, found {len(rows)}")
    for index, row in enumerate(rows, 1):
        _canonical_integer(row[1], label=f"grid fixture row {index} coefficient a")
        _canonical_integer(row[2], label=f"grid fixture row {index} coefficient b")
    expected = _canonical_grid_rows()
    _assert_rows_equal(rows, expected, label="grid fixture")
    if len({row[0] for row in rows}) != 438:
        raise ValueError("grid fixture IDs are not unique")
    if len({(row[1], row[2]) for row in rows}) != 438:
        raise ValueError("grid fixture pairs are not unique")
    return rows


def _validate_grid_result_scalars(rows: list[list[str]]) -> None:
    if len(rows) != 438:
        raise ValueError(f"grid result must contain 438 rows, found {len(rows)}")
    for index, row in enumerate(rows, 1):
        for column in (1, 2, 3, 5, 9, 11):
            _canonical_integer(
                row[column],
                label=f"grid result row {index} field {column + 1}",
            )
        if row[6]:
            for value in row[6].split(";"):
                parsed = _canonical_integer(
                    value,
                    label=f"grid result row {index} generator order",
                )
                if parsed < 1:
                    raise ValueError(f"grid result row {index} has an invalid order")
        if row[11] != "1":
            raise ValueError(f"grid result row {index} field match must be literal 1")


def _verify_grid(fixture_path: Path, result_path: Path) -> None:
    fixture_rows = _load_grid_fixture(fixture_path)
    _raw, result_rows = _read_csv_exact(
        result_path,
        label="grid result",
        header=GRID_RESULT_HEADER,
    )
    _validate_grid_result_scalars(result_rows)
    expected_rows: list[list[str]] = []
    for curve_id, a_text, b_text in fixture_rows:
        a = int(a_text, 10)
        b = int(b_text, 10)
        semantics = _evaluate_pair(a, b)
        expected_rows.append(
            [
                curve_id,
                a_text,
                b_text,
                str(semantics["discriminant"]),
                str(semantics["ours_type"]),
                str(semantics["ours_order"]),
                ";".join(str(value) for value in semantics["ours_generator_orders"]),
                str(semantics["ours_generators"]),
                str(semantics["sage_type"]),
                str(semantics["sage_order"]),
                str(semantics["sage_generators"]),
                "1",
            ]
        )
    _assert_rows_equal(result_rows, expected_rows, label="grid result")


def _regenerate_cases(
    mazur_rows: list[list[str]],
    *,
    random_sample_size: int,
) -> tuple[list[list[str]], dict[str, int]]:
    if type(random_sample_size) is not int or not (
        0 < random_sample_size <= CANONICAL_RANDOM_SIZE
    ):
        raise ValueError("random sample size must be in the range 1..10000")
    rows: list[list[str]] = []
    curated_pairs: set[tuple[int, int]] = set()
    for index, (expected_type, a_text, b_text, provenance) in enumerate(
        mazur_rows,
        1,
    ):
        pair = (int(a_text, 10), int(b_text, 10))
        curated_pairs.add(pair)
        rows.append(
            [
                f"curated_{index:04d}",
                "curated",
                expected_type,
                a_text,
                b_text,
                provenance,
            ]
        )

    generator = random.Random(SEED)
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
    draw_cap = 100 * random_sample_size + 1000
    while len(accepted_pairs) < random_sample_size:
        if stats["random_draw_attempts"] >= draw_cap:
            raise ValueError(f"random draw cap exhausted after {draw_cap} attempts")
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
            [
                f"random_{len(accepted_pairs):05d}",
                "random",
                "",
                str(a),
                str(b),
                f"random_seed_{SEED}",
            ]
        )
    return rows, stats


def _load_calibration_cases(
    path: Path,
    mazur_rows: list[list[str]],
    *,
    random_sample_size: int,
) -> tuple[bytes, list[list[str]], dict[str, int]]:
    raw, rows = _read_csv_exact(
        path,
        label="calibration cases",
        header=CALIBRATION_CASE_HEADER,
    )
    expected_rows, stats = _regenerate_cases(
        mazur_rows,
        random_sample_size=random_sample_size,
    )
    if len(rows) != 15 + random_sample_size:
        raise ValueError(
            f"calibration cases must contain {15 + random_sample_size} rows, "
            f"found {len(rows)}"
        )
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[int, int]] = set()
    for index, row in enumerate(rows, 1):
        a = _canonical_integer(
            row[3],
            label=f"calibration cases row {index} coefficient a",
        )
        b = _canonical_integer(
            row[4],
            label=f"calibration cases row {index} coefficient b",
        )
        if row[0] in seen_ids or (a, b) in seen_pairs:
            raise ValueError(f"calibration cases row {index} is duplicated")
        seen_ids.add(row[0])
        seen_pairs.add((a, b))
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            raise ValueError(f"calibration cases row {index} is singular")
    _assert_rows_equal(rows, expected_rows, label="calibration cases")
    return raw, rows, stats


def _validate_calibration_result_shape(
    rows: list[list[str]],
    *,
    random_sample_size: int,
    allow_noncanonical_fail: bool = False,
) -> None:
    minimum = len(SUMMARY_METRICS) + len(MAZUR_TYPES)
    if len(rows) < minimum:
        raise ValueError("calibration result is missing required typed rows")
    summary_rows = rows[: len(SUMMARY_METRICS)]
    type_rows = rows[len(SUMMARY_METRICS) : minimum]
    mismatch_rows = rows[minimum:]
    for index, (row, metric) in enumerate(zip(summary_rows, SUMMARY_METRICS, strict=True), 1):
        if row[0] != "summary" or row[1] != metric or row[2] == "":
            raise ValueError(f"calibration summary row {index} is not canonical")
        if any(row[column] != "" for column in range(3, len(row))):
            raise ValueError(f"calibration summary row {index} has wrong field occupancy")
    for offset, (row, torsion_type) in enumerate(
        zip(type_rows, MAZUR_TYPES, strict=True),
        1,
    ):
        if row[0] != "type_count" or row[2] == "" or row[3] != torsion_type:
            raise ValueError(f"calibration type-count row {offset} is not canonical")
        if row[1] != "" or any(row[column] != "" for column in range(4, len(row))):
            raise ValueError(f"calibration type-count row {offset} has wrong occupancy")
        value = _canonical_integer(row[2], label=f"type count {torsion_type}")
        if value < 0:
            raise ValueError(f"type count {torsion_type} is negative")
    for offset, row in enumerate(mismatch_rows, 1):
        if row[0] != "mismatch" or any(row[column] != "" for column in (1, 2, 3)):
            raise ValueError(f"calibration mismatch row {offset} has wrong occupancy")
        if (
            not row[4]
            or row[5] not in {"curated", "random"}
            or not row[7]
            or not row[8]
            or not row[9]
            or not row[10]
            or not row[11]
            or not row[12]
            or row[13] != "0"
            or not row[14]
        ):
            raise ValueError(f"calibration mismatch row {offset} is incomplete")
        for column in (7, 8, 10, 12):
            _canonical_integer(
                row[column],
                label=f"calibration mismatch row {offset} field {column + 1}",
            )
        codes = row[14].split(";")
        if codes != [code for code in DETAIL_CODES if code in set(codes)]:
            raise ValueError(f"calibration mismatch row {offset} has invalid detail order")

    values = {row[1]: row[2] for row in summary_rows}
    if values["status"] not in {"pass", "fail"}:
        raise ValueError("calibration status is invalid")
    integer_metrics = {
        "seed",
        "a_min",
        "a_max",
        "b_min",
        "b_max",
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
    }
    for metric in integer_metrics:
        _canonical_integer(values[metric], label=f"calibration metric {metric}")
    for metric in ("cases_sha256", "random_pairs_sha256", "outcomes_sha256"):
        _canonical_sha256(values[metric], label=f"calibration metric {metric}")
    if values["zero_coefficient_policy"] != "allowed_if_nonsingular":
        raise ValueError("calibration zero-coefficient policy is invalid")
    if values["max_seconds"] != str(CANONICAL_MAX_SECONDS):
        raise ValueError("calibration max-seconds value is not canonical")
    expected_status = "pass" if random_sample_size == CANONICAL_RANDOM_SIZE else "fail"
    if values["status"] != expected_status:
        raise ValueError("calibration release status is not canonical")
    if values["status"] != "pass" and not allow_noncanonical_fail:
        raise ValueError("calibration status=fail artifact is non-publishable")
    if mismatch_rows:
        raise ValueError("calibration result contains non-publishable mismatch rows")


def _recompute_calibration(
    rows: list[list[str]],
    *,
    max_seconds: float,
    clock=time.monotonic,
    compute_fn=None,
    reference_fn=None,
) -> tuple[list[dict[str, str]], dict[str, int], str]:
    start = clock()
    outcomes: list[dict[str, str]] = []
    type_counts = {torsion_type: 0 for torsion_type in MAZUR_TYPES}
    payload_parts: list[str] = []
    for processed, row in enumerate(rows):
        if clock() - start > max_seconds:
            raise TimeoutError(f"cooperative timeout after processed {processed} cases")
        case_id, case_kind, expected_type, a_text, b_text, _provenance = row
        semantics = _evaluate_pair(
            int(a_text, 10),
            int(b_text, 10),
            expected_type=expected_type,
            compute_fn=compute_fn,
            reference_fn=reference_fn,
        )
        outcome = {
            "case_id": case_id,
            "case_kind": case_kind,
            "expected_type": expected_type,
            "a": a_text,
            "b": b_text,
            "ours_type": str(semantics["ours_type"]),
            "ours_order": str(semantics["ours_order"]),
            "sage_type": str(semantics["sage_type"]),
            "sage_order": str(semantics["sage_order"]),
            "match": "1",
            "detail": "",
        }
        outcomes.append(outcome)
        type_counts[outcome["sage_type"]] += 1
        payload_parts.append(
            f"{case_id},{a_text},{b_text},{expected_type},"
            f"{outcome['ours_type']},{outcome['ours_order']},"
            f"{outcome['sage_type']},{outcome['sage_order']},1,\n"
        )
        if clock() - start > max_seconds:
            raise TimeoutError(
                f"cooperative timeout after processed {processed + 1} cases"
            )
    return outcomes, type_counts, _sha256("".join(payload_parts).encode("utf-8"))


def _summary_row(metric: str, value: str) -> list[str]:
    return ["summary", metric, value] + [""] * 12


def _type_count_row(torsion_type: str, value: int) -> list[str]:
    return ["type_count", "", str(value), torsion_type] + [""] * 11


def _verify_calibration(
    cases_path: Path,
    result_path: Path,
    mazur_rows: list[list[str]],
    *,
    random_sample_size: int,
    max_seconds: float,
    allow_noncanonical_fail: bool = False,
) -> None:
    raw_cases, case_rows, stats = _load_calibration_cases(
        cases_path,
        mazur_rows,
        random_sample_size=random_sample_size,
    )
    _raw_result, result_rows = _read_csv_exact(
        result_path,
        label="calibration result",
        header=CALIBRATION_RESULT_HEADER,
    )
    _validate_calibration_result_shape(
        result_rows,
        random_sample_size=random_sample_size,
        allow_noncanonical_fail=allow_noncanonical_fail,
    )
    outcomes, type_counts, outcomes_sha256 = _recompute_calibration(
        case_rows,
        max_seconds=max_seconds,
    )
    if len(outcomes) != 15 + random_sample_size:
        raise ValueError("calibration fresh outcome count is incomplete")
    if any(outcome["match"] != "1" for outcome in outcomes):
        raise ValueError("calibration fresh outcome contains a mismatch")
    covered = {
        outcome["sage_type"]
        for outcome in outcomes[:15]
        if outcome["match"] == "1"
    }
    if covered != set(MAZUR_TYPES):
        raise ValueError("calibration fresh outcomes do not cover all Mazur types")
    if sum(type_counts.values()) != len(case_rows):
        raise ValueError("calibration fresh type counts are incomplete")

    random_rows = [row for row in case_rows if row[1] == "random"]
    random_pairs_payload = "".join(
        f"{row[3]},{row[4]}\n" for row in random_rows
    ).encode("utf-8")
    pairs = {(int(row[3]), int(row[4])) for row in case_rows}
    total_redraw_count = (
        stats["singular_redraw_count"]
        + stats["curated_overlap_redraw_count"]
        + stats["duplicate_random_redraw_count"]
    )
    values = {
        "status": "pass" if random_sample_size == CANONICAL_RANDOM_SIZE else "fail",
        "seed": str(SEED),
        "a_min": str(A_MIN),
        "a_max": str(A_MAX),
        "b_min": str(B_MIN),
        "b_max": str(B_MAX),
        "zero_coefficient_policy": "allowed_if_nonsingular",
        "curated_case_count": "15",
        "random_case_count": str(random_sample_size),
        "total_case_count": str(len(case_rows)),
        "unique_pair_count": str(len(pairs)),
        "singular_inputs_in_cases": "0",
        "random_draw_attempts": str(stats["random_draw_attempts"]),
        "singular_redraw_count": str(stats["singular_redraw_count"]),
        "curated_overlap_redraw_count": str(stats["curated_overlap_redraw_count"]),
        "duplicate_random_redraw_count": str(stats["duplicate_random_redraw_count"]),
        "total_redraw_count": str(total_redraw_count),
        "random_a_zero_count": str(stats["random_a_zero_count"]),
        "random_b_zero_count": str(stats["random_b_zero_count"]),
        "random_any_zero_count": str(stats["random_any_zero_count"]),
        "match_count": str(len(case_rows)),
        "mismatch_count": "0",
        "all_15_mazur_types_covered": "1",
        "cases_sha256": _sha256(raw_cases),
        "random_pairs_sha256": _sha256(random_pairs_payload),
        "outcomes_sha256": outcomes_sha256,
        "max_seconds": str(CANONICAL_MAX_SECONDS),
    }
    expected_rows = [_summary_row(metric, values[metric]) for metric in SUMMARY_METRICS]
    expected_rows.extend(
        _type_count_row(torsion_type, type_counts[torsion_type])
        for torsion_type in MAZUR_TYPES
    )
    _assert_rows_equal(result_rows, expected_rows, label="calibration result")


def _check_result_inventory(environment_output: Path) -> None:
    directory = environment_output.parent
    if not directory.is_dir():
        raise ValueError("result directory does not exist")
    required = {
        "mazur_validation.csv",
        "grid_validation.csv",
        "calibration_summary.csv",
    }
    allowed = required | {"environment.json"}
    entries = list(directory.iterdir())
    unexpected = sorted(entry.name for entry in entries if entry.name not in allowed)
    if unexpected:
        raise ValueError(f"unexpected result file: {unexpected[0]}")
    nonfiles = sorted(entry.name for entry in entries if not entry.is_file())
    if nonfiles:
        raise ValueError(f"unexpected result entry: {nonfiles[0]}")
    names = {entry.name for entry in entries}
    missing = sorted(required - names)
    if missing:
        raise ValueError(f"missing required result file: {missing[0]}")


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _is_private_reference_name(name: str) -> bool:
    return "reference" in {
        component.casefold() for component in name.split(".") if component
    }


def _exact_reference_reexport(node: ast.ImportFrom) -> bool:
    return (
        node.level == 1
        and node.module == "reference"
        and [(alias.name, alias.asname) for alias in node.names]
        == [("compare_with_sage", None), ("sage_reference", None)]
    )


def _exact_public_reference_import(node: ast.ImportFrom) -> bool:
    if node.level != 0 or node.module != "rational_torsion":
        return False
    names = [(alias.name, alias.asname) for alias in node.names]
    return names in (
        [("sage_reference", None)],
        [("compute_torsion", None), ("sage_reference", None)],
    )


def _inspect_python_boundary(
    script_path: Path,
    *,
    allow_oracle_attributes: bool = False,
    allow_reference_reexport: bool = False,
    allow_public_reference_calls: bool = False,
    allow_public_reference_import: bool = False,
) -> bool:
    try:
        tree = ast.parse(script_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise ValueError(f"unable to inspect Python boundary: {exc}") from exc
    marker = "torsion_" + "subgroup"
    order_marker = "torsion_" + "order"
    forbidden_attributes = {marker, order_marker}
    public_reference_names = {"sage_reference", "compare_with_sage"}
    dynamic_names = {
        "__dict__",
        "__getattr__",
        "__getattribute__",
        "__import__",
        "__setattr__",
        "attrgetter",
        "delattr",
        "dir",
        "eval",
        "exec",
        "getattr",
        "getattr_static",
        "getmembers",
        "globals",
        "import_module",
        "locals",
        "methodcaller",
        "setattr",
        "vars",
    }
    parents = {
        id(child): parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    allowed_hasattr_nodes: set[int] = set()
    saw_reference_reexport = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "hasattr":
                if (
                    len(node.args) != 2
                    or node.keywords
                    or _static_string(node.args[1]) != "element"
                ):
                    raise ValueError("Python file uses non-reviewed dynamic reflection")
                allowed_hasattr_nodes.add(id(node.func))
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "hasattr":
                raise ValueError("Python file uses non-reviewed dynamic reflection")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in public_reference_names
                and not allow_public_reference_calls
            ):
                raise ValueError("Python file calls the public Sage reference API")
        if isinstance(node, ast.Attribute):
            attribute_name = node.attr.casefold()
            if attribute_name == "reference":
                raise ValueError("Python file accesses the private reference module")
            if attribute_name in forbidden_attributes and not allow_oracle_attributes:
                raise ValueError("Python file contains a direct Sage oracle attribute")
            if attribute_name in public_reference_names:
                raise ValueError("Python file accesses the public Sage reference API")
            if attribute_name in dynamic_names or attribute_name == "hasattr":
                raise ValueError("Python file uses non-reviewed dynamic reflection")
        if isinstance(node, ast.Name):
            if node.id in dynamic_names:
                raise ValueError("Python file uses non-reviewed dynamic reflection")
            if node.id == "hasattr" and id(node) not in allowed_hasattr_nodes:
                parent = parents.get(id(node))
                if not (
                    isinstance(parent, ast.Call)
                    and parent.func is node
                    and len(parent.args) == 2
                    and not parent.keywords
                    and _static_string(parent.args[1]) == "element"
                ):
                    raise ValueError("Python file uses non-reviewed dynamic reflection")
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_name = alias.name.casefold()
                if import_name == "importlib" or import_name.startswith("importlib."):
                    raise ValueError("Python file imports a dynamic import mechanism")
                if _is_private_reference_name(alias.name):
                    raise ValueError("Python file imports the private reference module")
        if isinstance(node, ast.ImportFrom):
            if allow_reference_reexport and _exact_reference_reexport(node):
                saw_reference_reexport = True
                continue
            module_name = (node.module or "").casefold()
            if module_name == "importlib" or module_name.startswith("importlib."):
                raise ValueError("Python file imports a dynamic import mechanism")
            if any(alias.name.casefold() in dynamic_names for alias in node.names):
                raise ValueError("Python file imports a dynamic reflection mechanism")
            private_module = (
                node.module is not None
                and _is_private_reference_name(node.module)
            )
            private_member = any(
                alias.name.casefold() == "reference" for alias in node.names
            )
            if private_module or private_member:
                raise ValueError("Python file imports the private reference module")
            imported_names = {alias.name.casefold() for alias in node.names}
            exposes_public_reference = bool(
                imported_names & public_reference_names or "*" in imported_names
            )
            if exposes_public_reference and not (
                allow_public_reference_import and _exact_public_reference_import(node)
            ):
                raise ValueError("Python file imports the public Sage reference API")
    return saw_reference_reexport


def _check_source_boundary(source_directory: Path) -> None:
    marker = "torsion_" + "subgroup"
    order_marker = "torsion_" + "order"
    occurrences: list[str] = []
    python_paths = sorted(source_directory.rglob("*.py"))
    if not python_paths:
        raise ValueError("rational torsion source contains no Python files")
    source_paths = {
        path.relative_to(source_directory).as_posix(): path for path in python_paths
    }
    if set(source_paths) != set(REVIEWED_SOURCE_SHA256):
        raise ValueError("rational torsion source inventory differs from reviewed input")
    for relative, expected_sha256 in REVIEWED_SOURCE_SHA256.items():
        actual_sha256 = hashlib.sha256(source_paths[relative].read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError(f"rational torsion source hash differs for {relative}")
    saw_root_reexport = False
    for path in python_paths:
        relative = path.relative_to(source_directory).as_posix()
        text = path.read_text(encoding="utf-8")
        if marker in text:
            occurrences.append(relative)
        if order_marker in text:
            raise ValueError(f"forbidden order oracle marker occurs in {relative}")
        if relative == "reference.py":
            _inspect_python_boundary(
                path,
                allow_oracle_attributes=True,
                allow_public_reference_calls=True,
            )
        elif relative == "__init__.py":
            saw_root_reexport = _inspect_python_boundary(
                path,
                allow_reference_reexport=True,
            )
        else:
            _inspect_python_boundary(path)
    if occurrences != ["reference.py"]:
        raise ValueError("Sage torsion oracle boundary is not confined to reference.py")
    if not saw_root_reexport:
        raise ValueError("root package has no exact reviewed reference re-export")


def _check_verifier_boundary(script_path: Path) -> None:
    _inspect_python_boundary(
        script_path,
        allow_public_reference_calls=True,
        allow_public_reference_import=True,
    )


def _safe_text(value, *, label: str) -> str:
    if type(value) is not str or not value or len(value) > 200:
        raise ValueError(f"environment field {label} must be a nonempty short string")
    if any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"environment field {label} contains a control character")
    normalized_text = unicodedata.normalize("NFKC", value)
    if len(normalized_text) > 200 or any(
        unicodedata.category(character).startswith("C")
        or unicodedata.category(character) in {"Zl", "Zp"}
        for character in normalized_text
    ):
        raise ValueError(f"environment field {label} has unsafe normalized text")
    if re.fullmatch(r"[A-Za-z0-9 .()+_-]+", normalized_text) is None:
        raise ValueError(f"environment field {label} has unsafe punctuation")
    normalized = normalized_text.casefold()
    compact = "".join(character for character in normalized if character.isalnum())
    identity_fragments = {
        "host" + "name",
        "user" + "name",
        "machine" + "id",
        "machine" + "identifier",
        "machine" + "guid",
        "device" + "identifier",
        "device" + "id",
        "host" + "id",
        "home",
        "cwd",
        "path",
        "os" + "user",
        "login",
        "account",
        "serial",
        "time" + "stamp",
        "time" + "zone",
        "api" + "key",
        "to" + "ken",
        "pass" + "word",
        "sec" + "ret",
    }
    local_values = {
        candidate
        for candidate in (
            getpass.getuser(),
            Path.home().name,
            str(Path.home()),
            platform.node(),
            socket.gethostname(),
        )
        if candidate
    }
    local_normalized = {
        unicodedata.normalize("NFKC", candidate).casefold()
        for candidate in local_values
    }
    local_compact = {
        "".join(character for character in candidate if character.isalnum())
        for candidate in local_normalized
    }
    looks_like_path = (
        "/" in normalized
        or "\\" in normalized
        or any(
            "SLASH" in unicodedata.name(character, "")
            or "SOLIDUS" in unicodedata.name(character, "")
            for character in normalized_text
        )
        or normalized.startswith("~")
        or re.match(r"^[a-z]:", normalized) is not None
    )
    uuid_pattern = re.search(
        r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
        r"[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])",
        normalized,
    )
    compact_identifier_pattern = re.search(
        r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])",
        normalized,
    )
    iso_time_pattern = re.search(
        r"(?<!\d)\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}"
        r"(?::\d{2}(?:\.\d+)?)?(?:z|[+-]\d{2}:?\d{2})?(?!\d)",
        normalized,
    )
    date_pattern = re.search(
        r"(?<![\d.])(?:19|20)\d{2}[-.](?:0?[1-9]|1[0-2])[-.]"
        r"(?:0?[1-9]|[12]\d|3[01])(?![\d.])",
        normalized,
    )
    reverse_date_pattern = re.search(
        r"(?<![\d.])(?:0?[1-9]|[12]\d|3[01])[-.]"
        r"(?:0?[1-9]|1[0-2])[-.](?:19|20)\d{2}(?![\d.])",
        normalized,
    )
    compact_time_pattern = re.search(
        r"(?<!\d)\d{8}t?\d{6}(?:z|[+-]\d{4})?(?!\d)",
        normalized,
    )
    rfc_time_pattern = re.search(
        r"\b(?:(?:mon|tue|wed|thu|fri|sat|sun),?\s+)?\d{1,2}\s+"
        r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}"
        r"(?:\s+\d{2}:\d{2}(?::\d{2})?(?:\s+(?:gmt|utc|[+-]\d{4}))?)?\b",
        normalized,
    )
    epoch_time_pattern = re.search(
        r"(?<!\d)(?:[12]\d{9}|[12]\d{12})(?!\d)",
        normalized,
    )
    long_digit_pattern = re.search(r"(?<!\d)\d{8,}(?!\d)", normalized)
    zone_pattern = re.search(
        r"\b(?:utc|gmt)\s*[+-]\s*\d{1,2}(?::?\d{2})?\b",
        normalized,
    )
    serial_label_pattern = re.search(
        r"(?<![a-z0-9])s[\s/._-]*n(?:o)?(?:\s*[:=#-]|\s+)",
        normalized,
    )
    mac_pattern = re.search(
        r"(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])",
        normalized,
    )
    cisco_mac_pattern = re.search(
        r"(?<![0-9a-f])(?:[0-9a-f]{4}\.){2}[0-9a-f]{4}(?![0-9a-f])",
        normalized,
    )
    ipv4_match = re.search(
        r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])",
        normalized,
    )
    ipv4_pattern = ipv4_match is not None and all(
        int(part) <= 255 for part in ipv4_match.group(0).split(".")
    )
    contains_local_value = any(
        (len(candidate) >= 3 and candidate in normalized)
        or normalized == candidate
        for candidate in local_normalized
    ) or any(
        candidate
        and ((len(candidate) >= 3 and candidate in compact) or compact == candidate)
        for candidate in local_compact
    )
    if (
        looks_like_path
        or any(fragment in compact for fragment in identity_fragments)
        or uuid_pattern is not None
        or compact_identifier_pattern is not None
        or iso_time_pattern is not None
        or date_pattern is not None
        or reverse_date_pattern is not None
        or compact_time_pattern is not None
        or rfc_time_pattern is not None
        or epoch_time_pattern is not None
        or long_digit_pattern is not None
        or zone_pattern is not None
        or serial_label_pattern is not None
        or mac_pattern is not None
        or cisco_mac_pattern is not None
        or ipv4_pattern
        or contains_local_value
    ):
        raise ValueError(f"environment field {label} contains identifying text")
    return value


def _reject_identity_content(value, *, label: str) -> None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            _safe_text(key, label=f"{label} key")
            _reject_identity_content(nested_value, label=f"{label}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested_value in enumerate(value):
            _reject_identity_content(nested_value, label=f"{label}[{index}]")
        return
    if type(value) is str:
        _safe_text(value, label=label)
        return
    if value is None or type(value) in {bool, int, float}:
        return
    raise ValueError(f"environment field {label} has an unsupported value type")


def _environment_bytes(environment: dict[str, object]) -> bytes:
    _reject_identity_content(environment, label="environment")
    if type(environment) is not dict or list(environment) != ENVIRONMENT_FIELDS:
        raise ValueError("environment object must contain exactly eight ordered fields")
    for field in ("os", "architecture", "cpu_model", "compiler_version"):
        _safe_text(environment[field], label=field)
    if environment["sage_version"] != "10.8":
        raise ValueError("environment Sage version must be 10.8")
    if environment["python_version"] != "3.13.7":
        raise ValueError("environment Python version must be 3.13.7")
    _safe_text(environment["sage_version"], label="sage_version")
    _safe_text(environment["python_version"], label="python_version")
    logical_cores = environment["logical_cores"]
    if type(logical_cores) is not int or logical_cores < 1:
        raise ValueError("environment logical core count must be a positive integer")
    memory_gib = environment["memory_gib"]
    if (
        type(memory_gib) is not float
        or not math.isfinite(memory_gib)
        or memory_gib <= 0
        or round(memory_gib, 1) != memory_gib
    ):
        raise ValueError("environment memory must be a positive one-decimal float")
    payload = (
        json.dumps(environment, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    parsed = json.loads(payload)
    if type(parsed["memory_gib"]) is not float:
        raise ValueError("environment memory JSON value must remain a float")
    return payload


def _first_line(command: list[str], *, label: str) -> str:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    if completed.returncode != 0:
        raise ValueError(f"unable to read {label}")
    lines = completed.stdout.splitlines()
    if not lines:
        raise ValueError(f"empty {label}")
    return lines[0].strip()


def _capture_environment() -> dict[str, object]:
    system = platform.system()
    architecture = platform.machine()
    if system == "Darwin":
        cpu_model = _first_line(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            label="CPU model",
        )
        memory_bytes = int(
            _first_line(["sysctl", "-n", "hw.memsize"], label="physical memory")
        )
    else:
        cpu_model = platform.processor().strip() or architecture
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
        memory_bytes = int(page_size * page_count)
    compiler_setting = os.environ.get("CXX", "clang++")
    compiler_command = shlex.split(compiler_setting)
    if not compiler_command:
        raise ValueError("configured compiler is empty")
    compiler_version = _first_line(compiler_command + ["--version"], label="compiler")
    logical_cores = os.cpu_count()
    if logical_cores is None:
        raise ValueError("logical core count is unavailable")
    environment: dict[str, object] = {
        "os": system,
        "architecture": architecture,
        "cpu_model": cpu_model,
        "logical_cores": int(logical_cores),
        "memory_gib": round(memory_bytes / (1024**3), 1),
        "sage_version": str(SAGE_VERSION),
        "python_version": platform.python_version(),
        "compiler_version": compiler_version,
    }
    _environment_bytes(environment)
    return environment


def _atomic_replace(source: Path, destination: Path) -> None:
    source.replace(destination)


def _write_staged(path: Path, payload: bytes, *, suffix: str) -> Path:
    staged: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=suffix,
            delete=False,
        ) as handle:
            staged = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return staged
    except Exception:
        if staged is not None and staged.exists():
            staged.unlink()
        raise


def _publish_environment_atomic(path: Path, payload: bytes) -> None:
    if not path.parent.is_dir():
        raise ValueError("environment destination directory does not exist")
    prior_exists = path.is_file()
    prior_bytes = path.read_bytes() if prior_exists else None
    staged: Path | None = None
    recovery: Path | None = None
    try:
        staged = _write_staged(path, payload, suffix=".stage")
        _atomic_replace(staged, path)
    except Exception:
        if prior_exists and (
            not path.is_file() or path.read_bytes() != prior_bytes
        ):
            assert prior_bytes is not None
            recovery = _write_staged(path, prior_bytes, suffix=".recovery")
            os.replace(recovery, path)
            if not path.is_file() or path.read_bytes() != prior_bytes:
                raise RuntimeError("environment rollback did not restore prior bytes")
        elif not prior_exists and (path.exists() or path.is_symlink()):
            if path.is_file() or path.is_symlink():
                path.unlink()
            else:
                raise RuntimeError("environment rollback found a non-file destination")
        raise
    finally:
        for candidate in (staged, recovery):
            if candidate is not None and candidate.exists():
                candidate.unlink()


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify exact torsion result artifacts")
    parser.add_argument(
        "--mazur-fixture",
        type=Path,
        default=ROOT / "data" / "mazur_representatives.csv",
    )
    parser.add_argument(
        "--mazur-result",
        type=Path,
        default=ROOT / "results" / "mazur_validation.csv",
    )
    parser.add_argument(
        "--grid-fixture",
        type=Path,
        default=ROOT / "data" / "coefficient_grid.csv",
    )
    parser.add_argument(
        "--grid-result",
        type=Path,
        default=ROOT / "results" / "grid_validation.csv",
    )
    parser.add_argument(
        "--calibration-cases",
        type=Path,
        default=ROOT / "data" / "calibration_cases.csv",
    )
    parser.add_argument(
        "--calibration-result",
        type=Path,
        default=ROOT / "results" / "calibration_summary.csv",
    )
    parser.add_argument(
        "--environment-output",
        type=Path,
        default=ROOT / "results" / "environment.json",
    )
    parser.add_argument(
        "--random-sample-size",
        type=int,
        default=CANONICAL_RANDOM_SIZE,
    )
    parser.add_argument("--max-seconds", type=float, default=float(CANONICAL_MAX_SECONDS))
    return parser


def _run_verification(arguments: argparse.Namespace) -> int:
    if type(arguments.random_sample_size) is not int or not (
        0 < arguments.random_sample_size <= CANONICAL_RANDOM_SIZE
    ):
        raise ValueError("random sample size must be in the range 1..10000")
    if not math.isfinite(arguments.max_seconds) or arguments.max_seconds <= 0:
        raise ValueError("max seconds must be finite and greater than zero")
    expected_result_paths = {
        arguments.mazur_result.resolve(),
        arguments.grid_result.resolve(),
        arguments.calibration_result.resolve(),
    }
    required_result_paths = {
        (arguments.environment_output.parent / name).resolve()
        for name in (
            "mazur_validation.csv",
            "grid_validation.csv",
            "calibration_summary.csv",
        )
    }
    if expected_result_paths != required_result_paths:
        raise ValueError("scientific result paths must use the canonical result inventory")
    if arguments.environment_output.name != "environment.json":
        raise ValueError("environment output name must be environment.json")
    _check_result_inventory(arguments.environment_output)
    _check_source_boundary(ROOT / "src" / "rational_torsion")
    _check_verifier_boundary(Path(__file__).resolve())
    mazur_rows = _verify_mazur(arguments.mazur_fixture, arguments.mazur_result)
    _verify_grid(arguments.grid_fixture, arguments.grid_result)
    _verify_calibration(
        arguments.calibration_cases,
        arguments.calibration_result,
        mazur_rows,
        random_sample_size=arguments.random_sample_size,
        max_seconds=arguments.max_seconds,
    )
    environment = _capture_environment()
    payload = _environment_bytes(environment)
    _publish_environment_atomic(arguments.environment_output, payload)
    return 15 + arguments.random_sample_size


def _error_line(exc: Exception) -> str:
    message = " ".join(str(exc).splitlines()).strip()
    return message or exc.__class__.__name__


def main(argv=None) -> int:
    arguments = _argument_parser().parse_args(argv)
    try:
        calibration_total = _run_verification(arguments)
    except Exception as exc:
        print(f"Verification error: {_error_line(exc)}", file=sys.stderr)
        return 1
    print("Mazur: 15/15 semantically verified")
    print("Grid: 438/438 semantically verified")
    print(
        f"Calibration: {calibration_total}/{calibration_total} "
        "semantically verified, 0 mismatches"
    )
    print("Environment: 8 anonymized fields recorded")
    print("Results verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
