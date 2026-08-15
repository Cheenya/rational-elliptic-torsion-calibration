from __future__ import annotations

import argparse
import csv
import io
import os
from pathlib import Path
import sys
import tempfile

from sage.all import EllipticCurve, QQ

from rational_torsion import compute_torsion, sage_reference
from rational_torsion.group import exact_order, subgroup_generated_by


GRID_HEADER = ["curve_id", "a", "b"]
RESULT_HEADER = [
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
HISTORICAL_HEADER = [
    "curve_id",
    "a",
    "b",
    "discriminant",
    "torsion_ours",
    "torsion_sage",
    "sage_match",
    "gens_ours",
    "gens_sage",
]


def _canonical_grid_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for a in range(-10, 11):
        for b in range(-10, 11):
            if -16 * (4 * a**3 + 27 * b**2) != 0:
                rows.append((f"curve_{len(rows) + 1:04d}", str(a), str(b)))
    return rows


def _read_csv(path: Path, *, label: str, require_lf_only: bool) -> list[list[str]]:
    if not path.is_file():
        raise ValueError(f"{label} does not exist")
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"{label} is empty")
    if not raw.endswith(b"\n"):
        raise ValueError(f"{label} must end with a newline")
    if require_lf_only and b"\r" in raw:
        raise ValueError(f"{label} must use LF line endings")
    try:
        text = raw.decode("utf-8")
        return list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"malformed {label}: {exc}") from exc


def _canonical_integer(text: str, *, label: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"{label} is not an integer: {text!r}") from exc
    if str(value) != text:
        raise ValueError(f"{label} is not canonical: {text!r}")
    return value


def _load_grid(path: Path) -> list[tuple[str, str, str]]:
    parsed = _read_csv(path, label="grid fixture", require_lf_only=True)
    if not parsed or parsed[0] != GRID_HEADER:
        raise ValueError("grid fixture header is not canonical")
    rows = [tuple(row) for row in parsed[1:]]
    if len(rows) != 438:
        raise ValueError(f"grid fixture must contain 438 rows, found {len(rows)}")
    if any(len(row) != 3 for row in rows):
        raise ValueError("grid fixture rows must contain exactly three fields")

    expected_rows = _canonical_grid_rows()
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[int, int]] = set()
    for index, (row, expected) in enumerate(zip(rows, expected_rows, strict=True), 1):
        curve_id, a_text, b_text = row
        if curve_id in seen_ids:
            raise ValueError(f"duplicate grid ID at row {index}: {curve_id}")
        seen_ids.add(curve_id)
        if curve_id != f"curve_{index:04d}":
            raise ValueError(f"malformed or out-of-sequence grid ID at row {index}")

        a = _canonical_integer(a_text, label=f"grid row {index} coefficient a")
        b = _canonical_integer(b_text, label=f"grid row {index} coefficient b")
        if not (-10 <= a <= 10 and -10 <= b <= 10):
            raise ValueError(f"grid row {index} coefficients are outside [-10,10]")
        pair = (a, b)
        if pair in seen_pairs:
            raise ValueError(f"duplicate grid pair at row {index}: {pair}")
        seen_pairs.add(pair)
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            raise ValueError(f"singular grid pair at row {index}: {pair}")
        if row != expected:
            raise ValueError(
                f"grid row {index} differs from canonical rule: {row!r} != {expected!r}"
            )

    if rows != expected_rows:
        raise ValueError("grid fixture does not match the canonical rule")
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


def _curve_failure(
    curve_id: str,
    a: int,
    b: int,
    ours_type: str,
    ours_order: int,
    sage_type: str,
    sage_order: int,
    invariant: str,
) -> ValueError:
    return ValueError(
        f"{curve_id} ({a},{b}): ours={ours_type}/{ours_order} "
        f"sage={sage_type}/{sage_order} invariant={invariant}"
    )


def _compute_result_rows(
    rows: list[tuple[str, str, str]],
) -> list[list[str]]:
    result_rows: list[list[str]] = []
    for curve_id, a_text, b_text in rows:
        a = int(a_text, 10)
        b = int(b_text, 10)
        expected_discriminant = -16 * (4 * a**3 + 27 * b**2)
        curve = EllipticCurve(QQ, [a, b])
        identity = curve(0)

        try:
            ours = compute_torsion(a, b)
        except Exception as exc:
            raise ValueError(
                f"{curve_id} ({a},{b}): own computation failed: {exc}"
            ) from exc
        try:
            reference = sage_reference(a, b)
        except Exception as exc:
            raise ValueError(
                f"{curve_id} ({a},{b}): Sage reference failed: {exc}"
            ) from exc

        own_points = list(ours.torsion_points)
        distinct_own_points = set(own_points)
        own_order = len(distinct_own_points)
        ours_type = ours.torsion_type
        sage_type = reference.torsion_type
        sage_order = reference.order

        def fail(invariant: str) -> None:
            raise _curve_failure(
                curve_id,
                a,
                b,
                ours_type,
                own_order,
                sage_type,
                sage_order,
                invariant,
            )

        if ours.a != a or ours.b != b:
            fail("own result model does not echo input")
        if ours.discriminant != expected_discriminant:
            fail("own discriminant mismatch")
        if len(own_points) != own_order:
            fail("own torsion points are not distinct")
        if identity not in distinct_own_points:
            fail("own torsion points omit identity")
        try:
            if any(point.curve() != curve for point in own_points):
                fail("own torsion point lies off input curve")
        except Exception:
            fail("own torsion point lies off input curve")
        if any(generator not in distinct_own_points for generator in ours.generators):
            fail("own generator is absent from torsion point set")

        generator_orders = []
        for generator in ours.generators:
            try:
                order = exact_order(generator)
            except Exception:
                fail("own generator order computation failed")
            if order is None:
                fail("own generator has no finite exact order")
            generator_orders.append(order)
        try:
            generated_points = set(subgroup_generated_by(curve, ours.generators))
        except Exception:
            fail("own subgroup generation failed")
        if generated_points != distinct_own_points:
            fail("own generators do not generate exact torsion point set")
        try:
            if any(generator.curve() != curve for generator in reference.generators):
                fail("Sage generator lies off input curve")
        except Exception:
            fail("Sage generator lies off input curve")
        if ours_type != sage_type:
            fail("type mismatch")
        if own_order != sage_order:
            fail("order mismatch")

        result_rows.append(
            [
                curve_id,
                a_text,
                b_text,
                str(expected_discriminant),
                ours_type,
                str(own_order),
                ";".join(str(order) for order in generator_orders),
                _serialize_generators(ours.generators),
                sage_type,
                str(sage_order),
                _serialize_generators(reference.generators),
                "1",
            ]
        )
    return result_rows


def _load_historical(path: Path) -> dict[tuple[int, int], dict[str, str]]:
    parsed = _read_csv(path, label="historical CSV", require_lf_only=False)
    if not parsed or parsed[0] != HISTORICAL_HEADER:
        raise ValueError("historical CSV header is not canonical")
    rows = parsed[1:]
    if len(rows) != 438:
        raise ValueError(f"historical CSV must contain 438 rows, found {len(rows)}")
    if any(len(row) != 9 for row in rows):
        raise ValueError("historical CSV rows must contain exactly nine fields")

    expected_pairs = {
        (int(a_text), int(b_text))
        for _, a_text, b_text in _canonical_grid_rows()
    }
    rows_by_pair: dict[tuple[int, int], dict[str, str]] = {}
    seen_ids: set[str] = set()
    for index, values in enumerate(rows, 1):
        row = dict(zip(HISTORICAL_HEADER, values, strict=True))
        curve_id = row["curve_id"]
        if not curve_id or curve_id in seen_ids:
            raise ValueError(f"historical curve_id is empty or duplicate at row {index}")
        seen_ids.add(curve_id)
        a = _canonical_integer(row["a"], label=f"historical row {index} coefficient a")
        b = _canonical_integer(row["b"], label=f"historical row {index} coefficient b")
        pair = (a, b)
        if pair in rows_by_pair:
            raise ValueError(f"duplicate historical pair at row {index}: {pair}")
        _canonical_integer(
            row["discriminant"],
            label=f"historical row {index} discriminant",
        )
        if not row["torsion_ours"] or not row["torsion_sage"]:
            raise ValueError(f"historical torsion type is empty at pair {pair}")
        if row["sage_match"] != "True":
            raise ValueError(
                f"historical pair {pair} field sage_match must be exactly True"
            )
        rows_by_pair[pair] = row

    if set(rows_by_pair) != expected_pairs:
        missing = sorted(expected_pairs - set(rows_by_pair))
        extra = sorted(set(rows_by_pair) - expected_pairs)
        raise ValueError(
            f"historical coefficient pair set mismatch: missing={missing[:1]} "
            f"extra={extra[:1]}"
        )
    return rows_by_pair


def _compare_historical(result_rows: list[list[str]], path: Path) -> None:
    historical_by_pair = _load_historical(path)
    for row in result_rows:
        a = int(row[1], 10)
        b = int(row[2], 10)
        pair = (a, b)
        historical = historical_by_pair[pair]
        comparisons = (
            ("torsion_ours", row[4]),
            ("torsion_sage", row[8]),
        )
        for field, fresh_value in comparisons:
            historical_value = historical[field]
            if fresh_value != historical_value:
                raise ValueError(
                    f"historical pair {pair} field {field} mismatch: "
                    f"fresh={fresh_value!r} historical={historical_value!r}"
                )
        if row[11] != "1":
            raise ValueError(f"fresh pair {pair} field match is not literal 1")


def _publish_atomic(path: Path, rows: list[list[str]]) -> None:
    if len(rows) != 438 or any(len(row) != 12 for row in rows):
        raise ValueError("result rows do not have the canonical 438-by-12 shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
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
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the exact rational torsion coefficient grid"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--historical", type=Path)
    arguments = parser.parse_args(argv)

    try:
        grid_rows = _load_grid(arguments.input)
        result_rows = _compute_result_rows(grid_rows)
        if arguments.historical is not None:
            _compare_historical(result_rows, arguments.historical)
        _publish_atomic(arguments.output, result_rows)
    except Exception as exc:
        print(f"Grid error: {exc}", file=sys.stderr)
        return 1

    print("Grid: 438/438 matches, 0 mismatches")
    if arguments.historical is not None:
        print("Historical: 438/438 matching rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
