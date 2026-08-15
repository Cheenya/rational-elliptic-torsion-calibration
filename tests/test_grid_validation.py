from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GRID_PATH = REPOSITORY_ROOT / "data" / "coefficient_grid.csv"
VALIDATOR_PATH = REPOSITORY_ROOT / "scripts" / "validate_grid.py"
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "rational_torsion"
GRID_HEADER = ("curve_id", "a", "b")
RESULT_HEADER = (
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
)
HISTORICAL_HEADER = (
    "curve_id",
    "a",
    "b",
    "discriminant",
    "torsion_ours",
    "torsion_sage",
    "sage_match",
    "gens_ours",
    "gens_sage",
)


def _expected_grid_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for a in range(-10, 11):
        for b in range(-10, 11):
            discriminant = -16 * (4 * a**3 + 27 * b**2)
            if discriminant != 0:
                rows.append((f"curve_{len(rows) + 1:04d}", str(a), str(b)))
    return rows


def _expected_grid_bytes() -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(GRID_HEADER)
    writer.writerows(_expected_grid_rows())
    return stream.getvalue().encode("utf-8")


def _load_validator_module():
    assert VALIDATOR_PATH.is_file(), f"Missing validator: {VALIDATOR_PATH.name}"
    spec = importlib.util.spec_from_file_location("validate_grid", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_bytes(header, rows, *, lineterminator: str = "\n") -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator=lineterminator)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _write_grid_case(path: Path, case_name: str) -> Path:
    rows = [list(row) for row in _expected_grid_rows()]
    header = list(GRID_HEADER)
    data: bytes | None = None

    if case_name == "missing":
        return path
    if case_name == "empty":
        data = b""
    elif case_name == "malformed":
        data = b'curve_id,a,b\n"unterminated,-10,-10\n'
    elif case_name == "non_utf8":
        data = b"curve_id,a,b\ncurve_0001,-10,\xff\n"
    elif case_name == "crlf":
        data = _csv_bytes(header, rows, lineterminator="\r\n")
    elif case_name == "unterminated":
        data = _csv_bytes(header, rows)[:-1]
    elif case_name == "wrong_header":
        header[0] = "id"
    elif case_name == "wrong_field_count":
        rows[0].append("extra")
    elif case_name == "too_few":
        rows.pop()
    elif case_name == "too_many":
        rows.append(["curve_0439", "10", "10"])
    elif case_name == "duplicate_id":
        rows[1][0] = rows[0][0]
    elif case_name == "malformed_id":
        rows[0][0] = "curve_1"
    elif case_name == "duplicate_pair":
        rows[1][1:] = rows[0][1:]
    elif case_name == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif case_name == "gap_id":
        rows[0][0] = "curve_0002"
    elif case_name == "noncanonical_integer":
        rows[0][1] = "-010"
    elif case_name == "outside_box":
        rows[0][1] = "-11"
    elif case_name == "singular_pair":
        rows[0][1:] = ["-3", "-2"]
    elif case_name == "wrong_canonical_row":
        rows[0][2] = "-9"
    elif data is None:
        raise AssertionError(f"unknown grid corruption: {case_name}")

    path.write_bytes(data if data is not None else _csv_bytes(header, rows))
    return path


def _synthetic_result_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for curve_id, a_text, b_text in _expected_grid_rows():
        a = int(a_text)
        b = int(b_text)
        rows.append(
            [
                curve_id,
                a_text,
                b_text,
                str(-16 * (4 * a**3 + 27 * b**2)),
                "Z/1",
                "1",
                "",
                "",
                "Z/1",
                "1",
                "",
                "1",
            ]
        )
    return rows


def _historical_rows_from_results(result_rows) -> list[list[str]]:
    rows = []
    for row in reversed(result_rows):
        rows.append(
            [
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[8],
                "True",
                f"own-generator-text-{row[0]}",
                f"sage-generator-text-{row[0]}",
            ]
        )
    return rows


def _temporary_outputs(output_path: Path) -> list[Path]:
    return sorted(output_path.parent.glob(f".{output_path.name}.*.tmp"))


def test_coefficient_grid_is_exact_rule_derived_fixture() -> None:
    data = GRID_PATH.read_bytes()

    assert data.endswith(b"\n")
    assert b"\r" not in data
    assert data.decode("utf-8").encode("utf-8") == data
    assert data == _expected_grid_bytes()
    assert len(_expected_grid_rows()) == 438
    assert _expected_grid_rows()[0] == ("curve_0001", "-10", "-10")
    assert _expected_grid_rows()[-1] == ("curve_0438", "10", "10")


def test_grid_omits_exact_singular_pairs() -> None:
    with GRID_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    emitted_pairs = {(int(row["a"]), int(row["b"])) for row in rows}
    full_box = {(a, b) for a in range(-10, 11) for b in range(-10, 11)}
    assert full_box - emitted_pairs == {(-3, -2), (-3, 2), (0, 0)}
    assert len(rows) == len(emitted_pairs) == 438
    assert all(-16 * (4 * a**3 + 27 * b**2) != 0 for a, b in emitted_pairs)


def test_validator_script_exists_and_exports_contract() -> None:
    validator = _load_validator_module()

    assert tuple(validator.GRID_HEADER) == GRID_HEADER
    assert tuple(validator.RESULT_HEADER) == RESULT_HEADER
    assert tuple(validator.HISTORICAL_HEADER) == HISTORICAL_HEADER
    assert callable(validator.main)


@pytest.mark.parametrize(
    "case_name",
    [
        "missing",
        "empty",
        "malformed",
        "non_utf8",
        "crlf",
        "unterminated",
        "wrong_header",
        "wrong_field_count",
        "too_few",
        "too_many",
        "duplicate_id",
        "malformed_id",
        "duplicate_pair",
        "reordered",
        "gap_id",
        "noncanonical_integer",
        "outside_box",
        "singular_pair",
        "wrong_canonical_row",
    ],
)
def test_invalid_grid_fails_before_algorithms_and_preserves_output(
    tmp_path,
    capsys,
    monkeypatch,
    case_name,
) -> None:
    validator = _load_validator_module()
    input_path = _write_grid_case(tmp_path / "grid.csv", case_name)
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def algorithm_must_not_run(*_args, **_kwargs):
        raise AssertionError("algorithm invoked before grid validation")

    monkeypatch.setattr(validator, "compute_torsion", algorithm_must_not_run)
    monkeypatch.setattr(validator, "sage_reference", algorithm_must_not_run)

    return_code = validator.main(
        ["--input", str(input_path), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert captured.out == ""
    assert "Grid error:" in captured.err
    assert "algorithm invoked" not in captured.err
    assert "Traceback" not in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


@pytest.mark.parametrize(
    ("case_name", "expected_message"),
    [
        ("wrong_header", "header"),
        ("too_few", "438"),
        ("noncanonical_pair", "canonical"),
        ("duplicate_pair", "pair"),
        ("changed_pair", "pair"),
        ("ours_type", "torsion_ours"),
        ("sage_type", "torsion_sage"),
        ("sage_match", "sage_match"),
    ],
)
def test_corrupt_historical_comparison_preserves_output(
    tmp_path,
    capsys,
    monkeypatch,
    case_name,
    expected_message,
) -> None:
    validator = _load_validator_module()
    result_rows = _synthetic_result_rows()
    historical_rows = _historical_rows_from_results(result_rows)
    header = list(HISTORICAL_HEADER)

    if case_name == "wrong_header":
        header[4] = "ours"
    elif case_name == "too_few":
        historical_rows.pop()
    elif case_name == "noncanonical_pair":
        historical_rows[0][1] = "+10"
    elif case_name == "duplicate_pair":
        historical_rows[0][1:3] = historical_rows[1][1:3]
    elif case_name == "changed_pair":
        historical_rows[0][1:3] = ["11", "10"]
    elif case_name == "ours_type":
        historical_rows[0][4] = "Z/2"
    elif case_name == "sage_type":
        historical_rows[0][5] = "Z/2"
    elif case_name == "sage_match":
        historical_rows[0][6] = "true"
    else:
        raise AssertionError(case_name)

    historical_path = tmp_path / "historical.csv"
    historical_path.write_bytes(_csv_bytes(header, historical_rows))
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)
    monkeypatch.setattr(
        validator,
        "_compute_result_rows",
        lambda _rows: [list(row) for row in result_rows],
    )

    return_code = validator.main(
        [
            "--input",
            str(GRID_PATH),
            "--output",
            str(output_path),
            "--historical",
            str(historical_path),
        ]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert captured.out == ""
    assert "Grid error:" in captured.err
    assert expected_message in captured.err
    assert "Traceback" not in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def test_generator_text_is_excluded_from_historical_comparison(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    validator = _load_validator_module()
    result_rows = _synthetic_result_rows()
    historical_rows = _historical_rows_from_results(result_rows)
    historical_rows[0][7] = "arbitrary, deliberately different own basis"
    historical_rows[0][8] = "arbitrary, deliberately different Sage basis"
    historical_path = tmp_path / "historical.csv"
    historical_path.write_bytes(_csv_bytes(HISTORICAL_HEADER, historical_rows))
    output_path = tmp_path / "result.csv"
    monkeypatch.setattr(
        validator,
        "_compute_result_rows",
        lambda _rows: [list(row) for row in result_rows],
    )

    return_code = validator.main(
        [
            "--input",
            str(GRID_PATH),
            "--output",
            str(output_path),
            "--historical",
            str(historical_path),
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    assert captured.out == (
        "Grid: 438/438 matches, 0 mismatches\n"
        "Historical: 438/438 matching rows\n"
    )
    assert output_path.read_bytes() == _csv_bytes(RESULT_HEADER, result_rows)
    assert _temporary_outputs(output_path) == []


@pytest.mark.parametrize("failing_side", ["own", "sage"])
def test_algorithm_failure_preserves_output_and_cleans_temp(
    tmp_path,
    capsys,
    monkeypatch,
    failing_side,
) -> None:
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def injected_failure(*_args, **_kwargs):
        raise RuntimeError(f"injected {failing_side} failure")

    if failing_side == "own":
        monkeypatch.setattr(validator, "compute_torsion", injected_failure)
    else:
        monkeypatch.setattr(validator, "sage_reference", injected_failure)

    return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert captured.out == ""
    assert "curve_0001" in captured.err
    assert "(-10,-10)" in captured.err
    assert f"injected {failing_side} failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


@pytest.mark.parametrize(
    ("mismatch_kind", "expected_sage_type", "expected_sage_order"),
    [
        ("type", "Z/2", 1),
        ("order", "Z/1", 2),
    ],
)
def test_explicit_own_sage_mismatch_reports_first_curve_and_preserves_output(
    tmp_path,
    capsys,
    monkeypatch,
    mismatch_kind,
    expected_sage_type,
    expected_sage_order,
) -> None:
    validator = _load_validator_module()
    real_reference = validator.sage_reference(-10, -10)
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def mismatching_reference(a, b):
        if (a, b) == (-10, -10):
            return type(real_reference)(
                torsion_type=expected_sage_type,
                order=expected_sage_order,
                generators=real_reference.generators,
            )
        return validator.sage_reference(a, b)

    monkeypatch.setattr(validator, "sage_reference", mismatching_reference)

    return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert captured.out == ""
    assert "curve_0001" in captured.err
    assert "(-10,-10)" in captured.err
    assert "ours=Z/1/1" in captured.err
    assert f"sage={expected_sage_type}/{expected_sage_order}" in captured.err
    assert mismatch_kind in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def test_replace_failure_preserves_output_and_cleans_exact_temp(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    validator = _load_validator_module()
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)
    monkeypatch.setattr(
        validator,
        "_compute_result_rows",
        lambda _rows: _synthetic_result_rows(),
    )

    def fail_replace(_temporary_path, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(validator.Path, "replace", fail_replace)

    return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code != 0
    assert captured.out == ""
    assert "injected replace failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def test_successful_publication_is_deterministic_through_main(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    validator = _load_validator_module()
    result_rows = _synthetic_result_rows()
    monkeypatch.setattr(
        validator,
        "_compute_result_rows",
        lambda _rows: [list(row) for row in result_rows],
    )
    first_output = tmp_path / "first.csv"
    second_output = tmp_path / "second.csv"

    first_return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(first_output)]
    )
    first_stdout = capsys.readouterr()
    second_return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(second_output)]
    )
    second_stdout = capsys.readouterr()

    assert first_return_code == second_return_code == 0
    assert first_stdout.err == second_stdout.err == ""
    assert first_stdout.out == second_stdout.out == (
        "Grid: 438/438 matches, 0 mismatches\n"
    )
    assert first_output.read_bytes() == second_output.read_bytes()
    assert first_output.read_bytes() == _csv_bytes(RESULT_HEADER, result_rows)
    assert _temporary_outputs(first_output) == []
    assert _temporary_outputs(second_output) == []


def test_complete_real_grid_matches_sage_and_has_exact_result_schema(
    tmp_path,
    capsys,
) -> None:
    validator = _load_validator_module()
    output_path = tmp_path / "grid-result.csv"

    return_code = validator.main(
        ["--input", str(GRID_PATH), "--output", str(output_path)]
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    assert captured.out == "Grid: 438/438 matches, 0 mismatches\n"
    raw = output_path.read_bytes()
    assert raw.endswith(b"\n")
    assert b"\r" not in raw
    assert raw.decode("utf-8").encode("utf-8") == raw

    with output_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert tuple(reader.fieldnames or ()) == RESULT_HEADER
    assert len(rows) == 438
    for expected, row in zip(_expected_grid_rows(), rows, strict=True):
        curve_id, a_text, b_text = expected
        a = int(a_text)
        b = int(b_text)
        assert (row["curve_id"], row["a"], row["b"]) == expected
        assert row["discriminant"] == str(-16 * (4 * a**3 + 27 * b**2))
        assert row["ours_type"] == row["sage_type"]
        assert row["ours_order"] == row["sage_order"]
        assert int(row["ours_order"]) >= 1
        assert int(row["sage_order"]) >= 1
        assert row["match"] == "1"
        assert " " not in row["ours_generators"]
        assert " " not in row["sage_generators"]
        if row["ours_generator_orders"]:
            assert all(
                int(order) >= 1
                for order in row["ours_generator_orders"].split(";")
            )
    assert _temporary_outputs(output_path) == []


def test_own_algorithm_remains_separate_from_sage_oracle() -> None:
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
