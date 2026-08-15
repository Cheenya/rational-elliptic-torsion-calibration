import csv
import importlib.util
from math import lcm
from pathlib import Path

import pytest
from sage.all import EllipticCurve, QQ

from rational_torsion import compute_torsion, compare_with_sage, sage_reference
from rational_torsion.group import exact_order, subgroup_generated_by


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPOSITORY_ROOT / "data" / "mazur_representatives.csv"
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "rational_torsion"
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_mazur.py"
EXPECTED_HEADER = ["expected_type", "a", "b", "provenance"]
EXPECTED_RESULT_HEADER = [
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
EXPECTED_ROWS = [
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


def _load_raw_fixture():
    assert FIXTURE_PATH.is_file(), f"Missing fixture: {FIXTURE_PATH.name}"
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as fixture_file:
        reader = csv.reader(fixture_file)
        rows = list(reader)
    assert rows, "Fixture is empty"
    return rows[0], rows[1:]


def _load_fixture_dicts():
    assert FIXTURE_PATH.is_file(), f"Missing fixture: {FIXTURE_PATH.name}"
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as fixture_file:
        reader = csv.DictReader(fixture_file)
        rows = list(reader)
    return reader.fieldnames, rows


def _load_validator_module():
    assert VALIDATOR_PATH.is_file(), f"Missing validator: {VALIDATOR_PATH.name}"
    spec = importlib.util.spec_from_file_location("validate_mazur", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_invalid_fixture(path, case_name):
    if case_name == "missing":
        return path.with_name("missing.csv")
    if case_name == "empty":
        path.write_bytes(b"")
        return path
    if case_name == "malformed":
        path.write_text('expected_type,a,b,provenance\n"unterminated\n', encoding="utf-8")
        return path

    header, rows = _load_raw_fixture()
    rows = [list(row) for row in rows]
    if case_name == "truncated":
        rows.pop()
    elif case_name == "duplicate_type":
        rows[1][0] = rows[0][0]
    elif case_name == "duplicate_pair":
        rows[1][1:3] = rows[0][1:3]
    elif case_name == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif case_name == "wrong_pair":
        rows[0][1] = "-11"
    elif case_name == "wrong_provenance":
        rows[0][3] = "calibration"
    else:
        raise AssertionError(f"Unknown invalid-fixture case: {case_name}")

    with path.open("w", encoding="utf-8", newline="") as fixture_file:
        writer = csv.writer(fixture_file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_fixture_file_exists():
    assert FIXTURE_PATH.is_file(), f"Missing fixture: {FIXTURE_PATH.name}"


def test_fixture_has_exact_canonical_contract():
    header, rows = _load_raw_fixture()

    assert header == EXPECTED_HEADER
    assert [tuple(row) for row in rows] == EXPECTED_ROWS
    assert len(rows) == 15
    assert FIXTURE_PATH.read_bytes().endswith(b"\n")
    assert b"\r" not in FIXTURE_PATH.read_bytes()

    types = [row[0] for row in rows]
    pairs = [(row[1], row[2]) for row in rows]
    assert len(types) == len(set(types)) == 15
    assert len(pairs) == len(set(pairs)) == 15
    assert set(types) == set(EXPECTED_DISCRIMINANTS)
    assert all(all(field != "" for field in row) for row in rows)
    assert all(row[3] for row in rows)
    assert all(str(int(value, 10)) == value for row in rows for value in row[1:3])


def test_fixture_curves_have_exact_short_models_and_discriminants():
    fieldnames, rows = _load_fixture_dicts()

    assert fieldnames == EXPECTED_HEADER
    for row in rows:
        expected_type = row["expected_type"]
        a = int(row["a"], 10)
        b = int(row["b"], 10)
        expected_discriminant = EXPECTED_DISCRIMINANTS[expected_type]
        curve = EllipticCurve(QQ, [a, b])

        assert tuple(curve.a_invariants()) == (0, 0, 0, a, b)
        assert int(curve.discriminant()) == expected_discriminant
        assert -16 * (4 * a**3 + 27 * b**2) == expected_discriminant
        assert expected_discriminant != 0


@pytest.mark.parametrize(
    "case_index",
    range(15),
    ids=[row[0] for row in EXPECTED_ROWS],
)
def test_all_mazur_types(case_index):
    _, rows = _load_fixture_dicts()
    row = rows[case_index]
    expected_type = row["expected_type"]
    expected_order = EXPECTED_ORDERS[expected_type]
    a = int(row["a"], 10)
    b = int(row["b"], 10)
    curve = EllipticCurve(QQ, [a, b])
    identity = curve(0)

    ours = compute_torsion(a, b)
    reference = sage_reference(a, b)
    comparison = compare_with_sage(a, b)

    assert ours.torsion_type == expected_type
    assert reference.torsion_type == expected_type
    assert reference.order == expected_order
    assert len(ours.torsion_points) == expected_order
    assert comparison.ours.torsion_type == expected_type
    assert comparison.reference.torsion_type == expected_type
    assert comparison.reference.order == expected_order
    assert comparison.match is True

    own_points = set(ours.torsion_points)
    assert len(own_points) == expected_order
    assert identity in own_points
    assert all(point.curve() == curve for point in own_points)
    assert all(generator in own_points for generator in ours.generators)

    generator_orders = [exact_order(generator) for generator in ours.generators]
    assert len(ours.generators) == EXPECTED_GENERATOR_COUNTS[expected_type]
    assert all(order is not None for order in generator_orders)
    assert lcm(*generator_orders) == EXPECTED_EXPONENTS[expected_type]
    generated_subgroup = set(subgroup_generated_by(curve, ours.generators))
    assert generated_subgroup == own_points


def test_sage_oracle_boundary_remains_isolated():
    source_by_name = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE_ROOT.glob("*.py"))
    }
    own_modules = ("model.py", "candidates.py", "group.py", "core.py")

    assert "torsion_subgroup" in source_by_name["reference.py"]
    assert all(
        "torsion_subgroup" not in source_by_name[module_name]
        for module_name in own_modules
    )
    assert all("torsion_order" not in source for source in source_by_name.values())
    assert all(
        "import reference" not in source_by_name[module_name]
        and "from .reference" not in source_by_name[module_name]
        for module_name in own_modules
    )


def test_validator_script_exists():
    assert VALIDATOR_PATH.is_file(), f"Missing validator: {VALIDATOR_PATH.name}"


@pytest.mark.parametrize(
    "case_name",
    [
        "missing",
        "empty",
        "malformed",
        "truncated",
        "duplicate_type",
        "duplicate_pair",
        "reordered",
        "wrong_pair",
        "wrong_provenance",
    ],
)
def test_validator_rejects_invalid_fixture_without_touching_output(
    tmp_path,
    capsys,
    monkeypatch,
    case_name,
):
    validator = _load_validator_module()
    input_path = _write_invalid_fixture(tmp_path / "input.csv", case_name)
    output_path = tmp_path / "result.csv"
    sentinel = b"existing result\n"
    output_path.write_bytes(sentinel)

    def algorithm_must_not_run(*_args, **_kwargs):
        raise AssertionError("algorithm invoked before fixture validation")

    monkeypatch.setattr(validator, "compute_torsion", algorithm_must_not_run)
    monkeypatch.setattr(validator, "sage_reference", algorithm_must_not_run)

    return_code = validator.main(
        ["--input", str(input_path), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert "Mazur error:" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert output_path.read_bytes() == sentinel


def test_validator_rejects_expected_order_mismatch_without_touching_output(
    tmp_path,
    capsys,
    monkeypatch,
):
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"
    sentinel = b"existing result\n"
    output_path.write_bytes(sentinel)
    monkeypatch.setattr(
        validator,
        "EXPECTED_ORDERS",
        {**validator.EXPECTED_ORDERS, "Z/1": 2},
    )

    return_code = validator.main(
        ["--input", str(FIXTURE_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert "Z/1" in captured.err
    assert output_path.read_bytes() == sentinel


def test_validator_computation_failure_preserves_output(
    tmp_path,
    capsys,
    monkeypatch,
):
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"
    sentinel = b"existing result\n"
    output_path.write_bytes(sentinel)

    def fail_computation(_a, _b):
        raise RuntimeError("injected computation failure")

    monkeypatch.setattr(validator, "compute_torsion", fail_computation)

    return_code = validator.main(
        ["--input", str(FIXTURE_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert "injected computation failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert list(tmp_path.glob(f".{output_path.name}.*.tmp")) == []


def test_validator_publication_failure_preserves_output_and_removes_temp(
    tmp_path,
    capsys,
    monkeypatch,
):
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"
    sentinel = b"existing result\n"
    output_path.write_bytes(sentinel)

    def fail_replace(_self, _target):
        raise OSError("injected publication failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    return_code = validator.main(
        ["--input", str(FIXTURE_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert "injected publication failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert list(tmp_path.glob(f".{output_path.name}.*.tmp")) == []


def test_validator_serializes_identity_as_o():
    validator = _load_validator_module()
    identity = EllipticCurve(QQ, [0, 1])(0)

    assert validator._serialize_point(identity) == "O"


def test_validator_publishes_complete_deterministic_result(tmp_path, capsys):
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"

    first_return_code = validator.main(
        ["--input", str(FIXTURE_PATH), "--output", str(output_path)]
    )
    first_summary = capsys.readouterr()
    first_bytes = output_path.read_bytes()

    second_return_code = validator.main(
        ["--input", str(FIXTURE_PATH), "--output", str(output_path)]
    )
    second_summary = capsys.readouterr()
    second_bytes = output_path.read_bytes()

    with output_path.open(newline="", encoding="utf-8") as result_file:
        reader = csv.DictReader(result_file)
        rows = list(reader)

    assert first_return_code == second_return_code == 0
    assert (
        first_summary.out
        == second_summary.out
        == "Mazur: 15/15 matches, 0 mismatches\n"
    )
    assert first_summary.err == second_summary.err == ""
    assert first_bytes == second_bytes
    assert reader.fieldnames == EXPECTED_RESULT_HEADER
    assert len(rows) == 15
    assert [row["expected_type"] for row in rows] == [row[0] for row in EXPECTED_ROWS]
    assert [row["a"] for row in rows] == [row[1] for row in EXPECTED_ROWS]
    assert [row["b"] for row in rows] == [row[2] for row in EXPECTED_ROWS]
    assert all(row["match"] == "1" for row in rows)
    assert all(row["ours_order"] == row["expected_order"] for row in rows)
    assert all(row["ours_point_count"] == row["expected_order"] for row in rows)
