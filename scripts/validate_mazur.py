from __future__ import annotations

import argparse
import csv
import io
from math import lcm
from pathlib import Path
import sys
import tempfile

from sage.all import EllipticCurve, QQ

from rational_torsion import compute_torsion, sage_reference
from rational_torsion.group import exact_order, subgroup_generated_by


INPUT_HEADER = ["expected_type", "a", "b", "provenance"]
RESULT_HEADER = [
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
CANONICAL_ROWS = [
    ("Z/1", "-10", "-10", "coefficient_grid"),
    ("Z/2", "-10", "-9", "coefficient_grid"),
    ("Z/2 x Z/2", "-9", "0", "coefficient_grid"),
    ("Z/3", "-9", "9", "coefficient_grid"),
    ("Z/4", "-2", "1", "coefficient_grid"),
    ("Z/5", "-432", "8208", "Adamova_reference"),
    ("Z/6", "0", "1", "coefficient_grid"),
    ("Z/7", "-43", "166", "Adamova_reference"),
    ("Z/8", "-44091", "3304854", "Adamova_reference"),
    ("Z/9", "-219", "1654", "calibration"),
    ("Z/10", "-58347", "3954150", "Cremona_66c1_short_model"),
    ("Z/12", "-1947", "108214", "calibration"),
    ("Z/2 x Z/4", "-12987", "-263466", "Cremona_15a1_short_model"),
    ("Z/2 x Z/6", "-24003", "1296702", "calibration"),
    ("Z/2 x Z/8", "-1386747", "368636886", "Cremona_210e2_short_model"),
]
EXPECTED_ORDERS = {
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
EXPECTED_EXPONENTS = {
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
EXPECTED_DISCRIMINANTS = {
    "Z/1": 20800,
    "Z/2": 29008,
    "Z/2 x Z/2": 46656,
    "Z/3": 11664,
    "Z/4": 80,
    "Z/5": -23944605696,
    "Z/6": -432,
    "Z/7": -6815744,
    "Z/8": 767341894828032,
    "Z/9": -509607936,
    "Z/10": 5958184124547072,
    "Z/12": -4586471424000,
    "Z/2 x Z/4": 110199605760000,
    "Z/2 x Z/6": 158687432294400,
    "Z/2 x Z/8": 111969852226928640000,
}


def _load_fixture(path: Path) -> list[tuple[str, str, str, str]]:
    if not path.is_file():
        raise ValueError("fixture does not exist")
    raw = path.read_bytes()
    if not raw:
        raise ValueError("fixture is empty")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError("fixture must use LF line endings and end with LF")
    try:
        text = raw.decode("utf-8")
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"malformed fixture: {exc}") from exc
    if not parsed or parsed[0] != INPUT_HEADER:
        raise ValueError("fixture header is not canonical")

    rows = [tuple(row) for row in parsed[1:]]
    if len(rows) != 15:
        raise ValueError(f"fixture must contain 15 rows, found {len(rows)}")
    if any(len(row) != 4 for row in rows):
        raise ValueError("fixture rows must contain exactly four fields")
    if rows != CANONICAL_ROWS:
        raise ValueError("fixture rows do not match the canonical contract")

    types = [row[0] for row in rows]
    pairs = [(row[1], row[2]) for row in rows]
    if len(set(types)) != 15 or len(set(pairs)) != 15:
        raise ValueError("fixture types and coefficient pairs must be unique")
    for expected_type, a_text, b_text, provenance in rows:
        if not provenance:
            raise ValueError(f"missing provenance for {expected_type}")
        try:
            a = int(a_text, 10)
            b = int(b_text, 10)
        except ValueError as exc:
            raise ValueError(f"noninteger coefficients for {expected_type}") from exc
        if str(a) != a_text or str(b) != b_text:
            raise ValueError(f"noncanonical coefficients for {expected_type}")
        discriminant = -16 * (4 * a**3 + 27 * b**2)
        if discriminant != EXPECTED_DISCRIMINANTS[expected_type]:
            raise ValueError(f"discriminant mismatch for {expected_type}")
        if discriminant == 0:
            raise ValueError(f"singular fixture curve for {expected_type}")
    return rows


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


def _compute_result_rows(
    rows: list[tuple[str, str, str, str]],
) -> list[list[str]]:
    result_rows = []
    for expected_type, a_text, b_text, provenance in rows:
        a = int(a_text, 10)
        b = int(b_text, 10)
        expected_order = EXPECTED_ORDERS[expected_type]
        curve = EllipticCurve(QQ, [a, b])
        identity = curve(0)

        ours = compute_torsion(a, b)
        reference = sage_reference(a, b)
        own_points = set(ours.torsion_points)
        own_order = len(own_points)
        generator_orders = [exact_order(point) for point in ours.generators]
        finite_generator_orders = all(order is not None for order in generator_orders)
        own_subgroup = set(subgroup_generated_by(curve, ours.generators))

        match = (
            ours.torsion_type == expected_type
            and reference.torsion_type == expected_type
            and reference.order == expected_order
            and own_order == expected_order
            and len(ours.torsion_points) == own_order
            and identity in own_points
            and all(point.curve() == curve for point in own_points)
            and len(ours.generators) == EXPECTED_GENERATOR_COUNTS[expected_type]
            and all(generator in own_points for generator in ours.generators)
            and finite_generator_orders
            and lcm(*generator_orders) == EXPECTED_EXPONENTS[expected_type]
            and own_subgroup == own_points
        )
        if not match:
            raise ValueError(
                f"mismatch at {expected_type} (a={a_text}, b={b_text})"
            )

        result_rows.append(
            [
                expected_type,
                str(expected_order),
                a_text,
                b_text,
                provenance,
                str(EXPECTED_DISCRIMINANTS[expected_type]),
                ours.torsion_type,
                str(own_order),
                str(own_order),
                ";".join(str(order) for order in generator_orders),
                _serialize_generators(ours.generators),
                reference.torsion_type,
                str(reference.order),
                _serialize_generators(reference.generators),
                "1",
            ]
        )
    return result_rows


def _publish_atomic(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer = csv.writer(temporary_file, lineterminator="\n")
            writer.writerow(RESULT_HEADER)
            writer.writerows(rows)
            temporary_file.flush()
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate all Mazur torsion types")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)

    try:
        fixture_rows = _load_fixture(arguments.input)
        result_rows = _compute_result_rows(fixture_rows)
        _publish_atomic(arguments.output, result_rows)
    except Exception as exc:
        print(f"Mazur error: {exc}", file=sys.stderr)
        return 1

    print("Mazur: 15/15 matches, 0 mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
