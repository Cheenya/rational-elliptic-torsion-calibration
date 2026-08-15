from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import importlib.util
import io
from pathlib import Path
import random

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAZUR_PATH = REPOSITORY_ROOT / "data" / "mazur_representatives.csv"
CASES_PATH = REPOSITORY_ROOT / "data" / "calibration_cases.csv"
RESULT_PATH = REPOSITORY_ROOT / "results" / "calibration_summary.csv"
REPRODUCE_PATH = REPOSITORY_ROOT / "scripts" / "reproduce.py"

CASE_HEADER = (
    "case_id",
    "case_kind",
    "expected_type",
    "a",
    "b",
    "provenance",
)
RESULT_HEADER = (
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
)
SUMMARY_METRICS = (
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
)
MAZUR_TYPES = (
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
)
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
    torsion_type: (0 if torsion_type == "Z/1" else 2 if " x " in torsion_type else 1)
    for torsion_type in MAZUR_TYPES
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


def _load_reproduce_module():
    assert REPRODUCE_PATH.is_file(), f"Missing script: {REPRODUCE_PATH.name}"
    spec = importlib.util.spec_from_file_location("reproduce", REPRODUCE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _csv_bytes(header, rows) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _curated_rows() -> list[tuple[str, ...]]:
    with MAZUR_PATH.open(newline="", encoding="utf-8") as stream:
        fixture_rows = list(csv.DictReader(stream))
    return [
        (
            f"curated_{index:04d}",
            "curated",
            row["expected_type"],
            row["a"],
            row["b"],
            row["provenance"],
        )
        for index, row in enumerate(fixture_rows, 1)
    ]


def _expected_case_rows(seed: int, sample_size: int) -> list[tuple[str, ...]]:
    rows = _curated_rows()
    curated_pairs = {(int(row[3]), int(row[4])) for row in rows}
    accepted: set[tuple[int, int]] = set()
    generator = random.Random(seed)
    while len(accepted) < sample_size:
        a = generator.randint(-10000, 10000)
        b = generator.randint(-10000, 10000)
        pair = (a, b)
        if -16 * (4 * a**3 + 27 * b**2) == 0:
            continue
        if pair in curated_pairs or pair in accepted:
            continue
        accepted.add(pair)
        rows.append(
            (
                f"random_{len(accepted):05d}",
                "random",
                "",
                str(a),
                str(b),
                f"random_seed_{seed}",
            )
        )
    return rows


def _write_expected_cases(path: Path, *, seed: int, sample_size: int) -> Path:
    path.write_bytes(_csv_bytes(CASE_HEADER, _expected_case_rows(seed, sample_size)))
    return path


def _temporary_outputs(output_path: Path) -> list[Path]:
    return sorted(output_path.parent.glob(f".{output_path.name}.*.tmp"))


def _read_result(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    return list(reader.fieldnames or []), rows


def _summary_values(rows: list[dict[str, str]]) -> dict[str, str]:
    return {
        row["metric"]: row["value"]
        for row in rows
        if row["record_type"] == "summary"
    }


def _run_arguments(
    cases_path: Path,
    output_path: Path,
    *,
    sample_size: int,
    max_seconds: str = "60",
) -> list[str]:
    return [
        "--seed",
        "20260220",
        "--sample-size",
        str(sample_size),
        "--cases",
        str(cases_path),
        "--output",
        str(output_path),
        "--max-seconds",
        max_seconds,
    ]


def test_reproduce_script_exports_case_generation_contract() -> None:
    reproduce = _load_reproduce_module()

    assert tuple(reproduce.CASE_HEADER) == CASE_HEADER
    assert tuple(reproduce.RESULT_HEADER) == RESULT_HEADER
    assert callable(reproduce.main)
    assert callable(reproduce._build_case_rows)
    assert callable(reproduce._serialize_case_rows)


def test_reviewed_type_order_and_generator_maps_are_exact() -> None:
    reproduce = _load_reproduce_module()

    assert reproduce.TYPE_ORDERS == TYPE_ORDERS
    assert reproduce.EXPECTED_GENERATOR_COUNTS == GENERATOR_COUNTS
    assert reproduce.EXPECTED_GENERATOR_EXPONENTS == GENERATOR_EXPONENTS


def test_small_seeded_case_generation_is_byte_deterministic() -> None:
    reproduce = _load_reproduce_module()
    expected_rows = _expected_case_rows(20260220, 25)

    first_rows, first_stats = reproduce._build_case_rows(
        MAZUR_PATH,
        seed=20260220,
        sample_size=25,
    )
    second_rows, second_stats = reproduce._build_case_rows(
        MAZUR_PATH,
        seed=20260220,
        sample_size=25,
    )

    assert first_rows == second_rows == expected_rows
    assert first_stats == second_stats
    assert first_stats["random_draw_attempts"] >= 25
    assert reproduce._serialize_case_rows(first_rows) == _csv_bytes(
        CASE_HEADER,
        expected_rows,
    )


def test_generation_redraw_order_overlap_and_zero_rules(monkeypatch) -> None:
    reproduce = _load_reproduce_module()
    draws = iter(
        [
            0,
            0,
            -10,
            -10,
            0,
            2,
            0,
            2,
            1,
            0,
            2,
            3,
        ]
    )

    class FixedRandom:
        def __init__(self, seed):
            assert seed == 20260220

        def randint(self, lower, upper):
            assert (lower, upper) == (-10000, 10000)
            return next(draws)

    monkeypatch.setattr(reproduce.random, "Random", FixedRandom)
    rows, stats = reproduce._build_case_rows(
        MAZUR_PATH,
        seed=20260220,
        sample_size=3,
    )

    assert rows[-3:] == [
        ("random_00001", "random", "", "0", "2", "random_seed_20260220"),
        ("random_00002", "random", "", "1", "0", "random_seed_20260220"),
        ("random_00003", "random", "", "2", "3", "random_seed_20260220"),
    ]
    assert stats == {
        "random_draw_attempts": 6,
        "singular_redraw_count": 1,
        "curated_overlap_redraw_count": 1,
        "duplicate_random_redraw_count": 1,
        "random_a_zero_count": 1,
        "random_b_zero_count": 1,
        "random_any_zero_count": 2,
    }


def test_case_generation_replace_failure_preserves_sentinel_and_cleans_temp(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = tmp_path / "cases.csv"
    sentinel = b"existing-cases\n"
    cases_path.write_bytes(sentinel)

    def fail_replace(_temporary_path, _destination):
        raise OSError("injected case replace failure")

    monkeypatch.setattr(reproduce.Path, "replace", fail_replace)
    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "3",
            "--cases",
            str(cases_path),
            "--generate-cases",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "injected case replace failure" in captured.err
    assert cases_path.read_bytes() == sentinel
    assert _temporary_outputs(cases_path) == []


def test_generation_draw_cap_preserves_sentinel_and_cleans_temp(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = tmp_path / "cases.csv"
    sentinel = b"existing-cases\n"
    cases_path.write_bytes(sentinel)

    class SingularRandom:
        def __init__(self, _seed):
            pass

        def randint(self, _lower, _upper):
            return 0

    monkeypatch.setattr(reproduce.random, "Random", SingularRandom)
    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "1",
            "--cases",
            str(cases_path),
            "--generate-cases",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "draw cap exhausted" in captured.err
    assert cases_path.read_bytes() == sentinel
    assert _temporary_outputs(cases_path) == []


@pytest.mark.parametrize(
    "case_name",
    ["missing", "changed", "malformed", "reordered", "duplicate", "incomplete"],
)
def test_invalid_mazur_source_blocks_generation_and_preserves_cases(
    tmp_path,
    capsys,
    monkeypatch,
    case_name,
) -> None:
    reproduce = _load_reproduce_module()
    fixture_path = tmp_path / "mazur.csv"
    with MAZUR_PATH.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        parsed = list(reader)
    header = parsed[0]
    rows = parsed[1:]
    data: bytes | None = None

    if case_name == "missing":
        pass
    elif case_name == "changed":
        rows[0][1] = "-11"
    elif case_name == "malformed":
        data = b'expected_type,a,b,provenance\n"unterminated\n'
    elif case_name == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    elif case_name == "duplicate":
        rows[1] = list(rows[0])
    elif case_name == "incomplete":
        rows.pop()
    else:
        raise AssertionError(case_name)
    if case_name != "missing":
        fixture_path.write_bytes(data if data is not None else _csv_bytes(header, rows))

    cases_path = tmp_path / "cases.csv"
    sentinel = b"existing-cases\n"
    cases_path.write_bytes(sentinel)
    monkeypatch.setattr(reproduce, "DEFAULT_MAZUR_PATH", fixture_path)
    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "1",
            "--cases",
            str(cases_path),
            "--generate-cases",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "Mazur fixture" in captured.err
    assert cases_path.read_bytes() == sentinel
    assert _temporary_outputs(cases_path) == []


@pytest.mark.parametrize("sample_size", ["0", "10001"])
def test_sample_size_gate_blocks_generation(
    tmp_path,
    capsys,
    sample_size,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = tmp_path / "cases.csv"
    sentinel = b"existing-cases\n"
    cases_path.write_bytes(sentinel)

    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            sample_size,
            "--cases",
            str(cases_path),
            "--generate-cases",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "1..10000" in captured.err
    assert cases_path.read_bytes() == sentinel


@pytest.mark.parametrize("max_seconds", ["0", "-1", "inf", "nan"])
def test_max_seconds_gate_precedes_algorithms(
    tmp_path,
    capsys,
    monkeypatch,
    max_seconds,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def algorithm_must_not_run(*_args, **_kwargs):
        raise AssertionError("algorithm invoked before max-seconds validation")

    monkeypatch.setattr(reproduce, "compute_torsion", algorithm_must_not_run)
    monkeypatch.setattr(reproduce, "sage_reference", algorithm_must_not_run)
    return_code = reproduce.main(
        _run_arguments(
            cases_path,
            output_path,
            sample_size=1,
            max_seconds=max_seconds,
        )
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "max seconds" in captured.err
    assert "algorithm invoked" not in captured.err
    assert output_path.read_bytes() == sentinel


def test_noncanonical_seed_cannot_produce_release_pass(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    rows = _expected_case_rows(1, 10000)
    cases_path = tmp_path / "cases.csv"
    cases_path.write_bytes(_csv_bytes(CASE_HEADER, rows))
    output_path = tmp_path / "result.csv"

    def matching_outcome(row):
        torsion_type = row[2] or "Z/1"
        return (
            {"sage_type": torsion_type, "match": "1"},
            f"{row[0]},synthetic-match\n",
        )

    monkeypatch.setattr(reproduce, "_evaluate_case", matching_outcome)
    return_code = reproduce.main(
        [
            "--seed",
            "1",
            "--sample-size",
            "10000",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
            "--max-seconds",
            "3600",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    _, result_rows = _read_result(output_path)
    summary = _summary_values(result_rows)
    assert summary["seed"] == "1"
    assert summary["match_count"] == "10015"
    assert summary["mismatch_count"] == "0"
    assert summary["all_15_mazur_types_covered"] == "1"
    assert summary["status"] == "fail"


def test_noncanonical_max_seconds_cannot_produce_release_pass(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    rows = _expected_case_rows(20260220, 10000)
    cases_path = tmp_path / "cases.csv"
    cases_path.write_bytes(_csv_bytes(CASE_HEADER, rows))
    output_path = tmp_path / "result.csv"

    def matching_outcome(row):
        torsion_type = row[2] or "Z/1"
        return (
            {"sage_type": torsion_type, "match": "1"},
            f"{row[0]},synthetic-match\n",
        )

    monkeypatch.setattr(reproduce, "_evaluate_case", matching_outcome)
    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "10000",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
            "--max-seconds",
            "7200",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    _, result_rows = _read_result(output_path)
    summary = _summary_values(result_rows)
    assert summary["max_seconds"] == "7200"
    assert summary["match_count"] == "10015"
    assert summary["mismatch_count"] == "0"
    assert summary["all_15_mazur_types_covered"] == "1"
    assert summary["status"] == "fail"


def test_unrecognized_reference_type_cannot_hide_from_release_type_counts(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    rows = _expected_case_rows(20260220, 10000)
    cases_path = tmp_path / "cases.csv"
    cases_path.write_bytes(_csv_bytes(CASE_HEADER, rows))
    output_path = tmp_path / "result.csv"

    def matching_outcome(row):
        torsion_type = row[2] or "Z/1"
        if row[0] == "random_00001":
            torsion_type = "Z/999"
        return (
            {"sage_type": torsion_type, "match": "1"},
            f"{row[0]},synthetic-match\n",
        )

    monkeypatch.setattr(reproduce, "_evaluate_case", matching_outcome)
    return_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "10000",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
            "--max-seconds",
            "3600",
        ]
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    _, result_rows = _read_result(output_path)
    summary = _summary_values(result_rows)
    count_sum = sum(
        int(row["value"])
        for row in result_rows
        if row["record_type"] == "type_count"
    )
    assert count_sum == 10014
    assert summary["match_count"] == "10015"
    assert summary["all_15_mazur_types_covered"] == "1"
    assert summary["status"] == "fail"


def test_cli_modes_enforce_output_contract(tmp_path, capsys) -> None:
    reproduce = _load_reproduce_module()
    cases_path = tmp_path / "cases.csv"
    output_path = tmp_path / "result.csv"
    cases_sentinel = b"existing-cases\n"
    result_sentinel = b"existing-result\n"
    cases_path.write_bytes(cases_sentinel)
    output_path.write_bytes(result_sentinel)

    generation_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "1",
            "--cases",
            str(cases_path),
            "--output",
            str(output_path),
            "--generate-cases",
        ]
    )
    generation_console = capsys.readouterr()
    result_code = reproduce.main(
        [
            "--seed",
            "20260220",
            "--sample-size",
            "1",
            "--cases",
            str(cases_path),
        ]
    )
    result_console = capsys.readouterr()

    assert generation_code == result_code == 1
    assert generation_console.out == result_console.out == ""
    assert "not allowed" in generation_console.err
    assert "required" in result_console.err
    assert cases_path.read_bytes() == cases_sentinel
    assert output_path.read_bytes() == result_sentinel


def test_small_real_result_mode_is_deterministic_and_typed(
    tmp_path,
    capsys,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    first_output = tmp_path / "first.csv"
    second_output = tmp_path / "second.csv"

    first_code = reproduce.main(_run_arguments(cases_path, first_output, sample_size=1))
    first_console = capsys.readouterr()
    second_code = reproduce.main(
        _run_arguments(cases_path, second_output, sample_size=1)
    )
    second_console = capsys.readouterr()

    assert first_code == second_code == 0
    assert first_console == second_console
    assert first_console.err == ""
    assert first_console.out == (
        "Calibration: 16/16 matches, 0 mismatches\n"
        "Mazur coverage: 15/15 types\n"
    )
    assert first_output.read_bytes() == second_output.read_bytes()
    raw = first_output.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    header, rows = _read_result(first_output)
    assert tuple(header) == RESULT_HEADER
    summary_rows = [row for row in rows if row["record_type"] == "summary"]
    count_rows = [row for row in rows if row["record_type"] == "type_count"]
    mismatch_rows = [row for row in rows if row["record_type"] == "mismatch"]
    assert tuple(row["metric"] for row in summary_rows) == SUMMARY_METRICS
    assert [row["torsion_type"] for row in count_rows] == list(MAZUR_TYPES)
    assert [int(row["value"]) for row in count_rows] == [2] + [1] * 14
    assert mismatch_rows == []
    summary = _summary_values(rows)
    assert summary["status"] == "fail"
    assert summary["match_count"] == "16"
    assert summary["mismatch_count"] == "0"
    assert summary["all_15_mazur_types_covered"] == "1"
    assert summary["max_seconds"] == "60"
    assert _temporary_outputs(first_output) == []
    assert _temporary_outputs(second_output) == []


def test_each_algorithm_is_called_once_per_case_in_canonical_order(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    expected_rows = _expected_case_rows(20260220, 2)
    expected_pairs = [(int(row[3]), int(row[4])) for row in expected_rows]
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=2,
    )
    output_path = tmp_path / "result.csv"
    real_own = reproduce.compute_torsion
    real_reference = reproduce.sage_reference
    own_calls: list[tuple[int, int]] = []
    reference_calls: list[tuple[int, int]] = []
    interleaved_calls: list[tuple[str, int, int]] = []

    def own_spy(a, b):
        own_calls.append((a, b))
        interleaved_calls.append(("own", a, b))
        return real_own(a, b)

    def reference_spy(a, b):
        reference_calls.append((a, b))
        interleaved_calls.append(("sage", a, b))
        return real_reference(a, b)

    monkeypatch.setattr(reproduce, "compute_torsion", own_spy)
    monkeypatch.setattr(reproduce, "sage_reference", reference_spy)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=2)
    )
    captured = capsys.readouterr()

    assert return_code == 0
    assert captured.err == ""
    assert own_calls == reference_calls == expected_pairs
    assert interleaved_calls == [
        event
        for a, b in expected_pairs
        for event in (("own", a, b), ("sage", a, b))
    ]


def _write_corrupt_cases(
    path: Path,
    *,
    case_name: str,
    seed: int = 20260220,
    sample_size: int = 2,
) -> Path:
    rows = [list(row) for row in _expected_case_rows(seed, sample_size)]
    header = list(CASE_HEADER)
    data: bytes | None = None
    first_random = 15

    if case_name == "missing":
        return path
    if case_name == "empty":
        data = b""
    elif case_name == "malformed":
        data = b'case_id,case_kind,expected_type,a,b,provenance\n"unterminated\n'
    elif case_name == "truncated":
        rows.pop()
    elif case_name == "reordered":
        rows[first_random], rows[first_random + 1] = (
            rows[first_random + 1],
            rows[first_random],
        )
    elif case_name == "duplicate":
        rows[first_random + 1][3:5] = rows[first_random][3:5]
    elif case_name == "singular":
        rows[first_random][3:5] = ["0", "0"]
    elif case_name == "noncanonical":
        rows[first_random][3] = f"+{rows[first_random][3]}"
    elif case_name == "wrong_seed_provenance":
        rows[first_random][5] = "random_seed_1"
    elif case_name == "wrong_curated":
        rows[0][2] = "Z/2"
    elif case_name == "wrong_random":
        rows[first_random][4] = str(int(rows[first_random][4]) + 1)
    elif case_name == "wrong_header":
        header[0] = "id"
    else:
        raise AssertionError(case_name)

    path.write_bytes(data if data is not None else _csv_bytes(header, rows))
    return path


@pytest.mark.parametrize(
    "case_name",
    [
        "missing",
        "empty",
        "malformed",
        "truncated",
        "reordered",
        "duplicate",
        "singular",
        "noncanonical",
        "wrong_seed_provenance",
        "wrong_curated",
        "wrong_random",
        "wrong_header",
    ],
)
def test_invalid_cases_fail_before_algorithms_and_preserve_result(
    tmp_path,
    capsys,
    monkeypatch,
    case_name,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_corrupt_cases(tmp_path / "cases.csv", case_name=case_name)
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def algorithm_must_not_run(*_args, **_kwargs):
        raise AssertionError("algorithm invoked before case validation")

    monkeypatch.setattr(reproduce, "compute_torsion", algorithm_must_not_run)
    monkeypatch.setattr(reproduce, "sage_reference", algorithm_must_not_run)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=2)
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "Calibration error:" in captured.err
    assert "algorithm invoked" not in captured.err
    assert "Traceback" not in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


@pytest.mark.parametrize("failing_side", ["own", "sage"])
def test_algorithm_exception_preserves_result_and_cleans_temp(
    tmp_path,
    capsys,
    monkeypatch,
    failing_side,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)

    def injected_failure(*_args, **_kwargs):
        raise RuntimeError(f"injected {failing_side} failure")

    if failing_side == "own":
        monkeypatch.setattr(reproduce, "compute_torsion", injected_failure)
    else:
        monkeypatch.setattr(reproduce, "sage_reference", injected_failure)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=1)
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "curated_0001" in captured.err
    assert f"injected {failing_side} failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def test_cooperative_timeout_preserves_result_and_reports_processed_count(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)
    clock_values = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(reproduce, "_monotonic", lambda: next(clock_values))

    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=1, max_seconds="1")
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "timeout" in captured.err.lower()
    assert "processed 1" in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


@pytest.mark.parametrize("failure_kind", ["serialization", "replace"])
def test_result_publication_fault_preserves_sentinel_and_cleans_exact_temp(
    tmp_path,
    capsys,
    monkeypatch,
    failure_kind,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)
    monkeypatch.setattr(
        reproduce,
        "_run_calibration",
        lambda *_args, **_kwargs: ([], 16, 0, 15),
    )
    if failure_kind == "serialization":
        monkeypatch.setattr(
            reproduce,
            "_serialize_result_rows",
            lambda _rows: (_ for _ in ()).throw(
                OSError("injected serialization failure")
            ),
        )
    else:
        monkeypatch.setattr(reproduce, "_serialize_result_rows", lambda _rows: b"ok\n")

        def fail_replace(_temporary_path, _destination):
            raise OSError("injected result replace failure")

        monkeypatch.setattr(reproduce.Path, "replace", fail_replace)

    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=1)
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    expected_error = (
        "injected serialization failure"
        if failure_kind == "serialization"
        else "injected result replace failure"
    )
    assert expected_error in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def _assert_fixed_typed_schema(rows: list[dict[str, str]]) -> None:
    for row in rows:
        if row["record_type"] == "summary":
            assert row["metric"]
            assert row["value"] != ""
            assert all(
                row[column] == ""
                for column in RESULT_HEADER[3:]
            )
        elif row["record_type"] == "type_count":
            assert row["metric"] == ""
            assert row["value"] != ""
            assert row["torsion_type"]
            assert all(
                row[column] == ""
                for column in RESULT_HEADER[4:]
            )
        elif row["record_type"] == "mismatch":
            assert row["metric"] == row["value"] == row["torsion_type"] == ""
            assert all(row[column] != "" for column in ("case_id", "case_kind", "a", "b"))
            assert all(
                row[column] != ""
                for column in (
                    "ours_type",
                    "ours_order",
                    "sage_type",
                    "sage_order",
                    "match",
                    "detail",
                )
            )
            assert row["match"] == "0"
        else:
            raise AssertionError(f"unknown record type: {row['record_type']!r}")


@pytest.mark.parametrize(
    ("mismatch_kind", "expected_detail"),
    [
        ("type", "expected_type;torsion_type;torsion_order"),
        ("order", "torsion_order"),
        ("expected", "generator_order;expected_type;torsion_order"),
        ("internal", "model_echo"),
    ],
)
def test_scientific_mismatch_is_published_as_typed_fail_row(
    tmp_path,
    capsys,
    monkeypatch,
    mismatch_kind,
    expected_detail,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    output_path.write_bytes(b"existing-result\n")
    real_own = reproduce.compute_torsion
    real_reference = reproduce.sage_reference

    def own_wrapper(a, b):
        result = real_own(a, b)
        if (a, b) != (-1386747, 368636886):
            return result
        if mismatch_kind == "expected":
            return replace(result, torsion_type="Z/2")
        if mismatch_kind == "internal":
            return replace(result, a=a + 1)
        return result

    def reference_wrapper(a, b):
        result = real_reference(a, b)
        if (a, b) != (-1386747, 368636886):
            return result
        if mismatch_kind in {"type", "expected"}:
            return replace(result, torsion_type="Z/2")
        if mismatch_kind == "order":
            return replace(result, order=result.order + 1)
        return result

    monkeypatch.setattr(reproduce, "compute_torsion", own_wrapper)
    monkeypatch.setattr(reproduce, "sage_reference", reference_wrapper)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=1)
    )
    captured = capsys.readouterr()

    assert return_code == 2
    assert captured.err == ""
    assert captured.out == (
        "Calibration: 15/16 matches, 1 mismatches\n"
        "Mazur coverage: 14/15 types\n"
    )
    header, rows = _read_result(output_path)
    assert tuple(header) == RESULT_HEADER
    _assert_fixed_typed_schema(rows)
    mismatch_rows = [row for row in rows if row["record_type"] == "mismatch"]
    assert len(mismatch_rows) == 1
    assert mismatch_rows[0]["case_id"] == "curated_0015"
    assert mismatch_rows[0]["detail"] == expected_detail
    summary = _summary_values(rows)
    assert summary["status"] == "fail"
    assert summary["match_count"] == "15"
    assert summary["mismatch_count"] == "1"
    assert summary["all_15_mazur_types_covered"] == "0"
    assert _temporary_outputs(output_path) == []


def test_every_scientific_mismatch_is_retained_in_case_order(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=2,
    )
    output_path = tmp_path / "result.csv"
    real_own = reproduce.compute_torsion

    def wrong_model_echo(a, b):
        return replace(real_own(a, b), a=a + 1)

    monkeypatch.setattr(reproduce, "compute_torsion", wrong_model_echo)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=2)
    )
    captured = capsys.readouterr()

    assert return_code == 2
    assert captured.err == ""
    assert "0/17 matches, 17 mismatches" in captured.out
    _, rows = _read_result(output_path)
    mismatch_rows = [row for row in rows if row["record_type"] == "mismatch"]
    assert [row["case_id"] for row in mismatch_rows] == [
        row[0] for row in _expected_case_rows(20260220, 2)
    ]
    assert all(row["detail"] == "model_echo" for row in mismatch_rows)
    assert _summary_values(rows)["status"] == "fail"


def test_scientific_fail_report_replace_fault_preserves_previous_result(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    reproduce = _load_reproduce_module()
    cases_path = _write_expected_cases(
        tmp_path / "cases.csv",
        seed=20260220,
        sample_size=1,
    )
    output_path = tmp_path / "result.csv"
    sentinel = b"existing-result\n"
    output_path.write_bytes(sentinel)
    real_own = reproduce.compute_torsion

    def wrong_model_echo(a, b):
        return replace(real_own(a, b), a=a + 1)

    def fail_replace(_temporary_path, _destination):
        raise OSError("injected scientific fail-report replace failure")

    monkeypatch.setattr(reproduce, "compute_torsion", wrong_model_echo)
    monkeypatch.setattr(reproduce.Path, "replace", fail_replace)
    return_code = reproduce.main(
        _run_arguments(cases_path, output_path, sample_size=1)
    )
    captured = capsys.readouterr()

    assert return_code == 1
    assert captured.out == ""
    assert "scientific fail-report replace failure" in captured.err
    assert output_path.read_bytes() == sentinel
    assert _temporary_outputs(output_path) == []


def test_all_internal_failure_codes_use_fixed_order(monkeypatch) -> None:
    reproduce = _load_reproduce_module()
    row = _expected_case_rows(20260220, 1)[1]
    a = int(row[3])
    b = int(row[4])
    baseline_own = reproduce.compute_torsion(a, b)
    baseline_reference = reproduce.sage_reference(a, b)
    foreign_point = reproduce.sage_reference(0, 1).generators[0]
    corrupted_own = replace(
        baseline_own,
        a=a + 1,
        discriminant=baseline_own.discriminant + 1,
        torsion_type="Z/3",
        torsion_points=[foreign_point, foreign_point],
    )
    corrupted_reference = replace(
        baseline_reference,
        generators=[foreign_point],
    )

    monkeypatch.setattr(reproduce, "compute_torsion", lambda _a, _b: corrupted_own)
    monkeypatch.setattr(
        reproduce,
        "sage_reference",
        lambda _a, _b: corrupted_reference,
    )
    monkeypatch.setattr(reproduce, "exact_order", lambda _point: None)
    outcome, payload = reproduce._evaluate_case(row)

    expected_detail = ";".join(reproduce.DETAIL_CODES)
    assert outcome["match"] == "0"
    assert outcome["detail"] == expected_detail
    assert payload.endswith(f",0,{expected_detail}\n")


@pytest.mark.parametrize(
    ("torsion_type", "reference_order", "required_codes"),
    [
        ("Z/999", 1, {"torsion_type", "torsion_order"}),
        ("Z/2", 1, {"torsion_order"}),
    ],
)
def test_unknown_or_label_incompatible_type_order_is_a_mismatch(
    monkeypatch,
    torsion_type,
    reference_order,
    required_codes,
) -> None:
    reproduce = _load_reproduce_module()
    row = _expected_case_rows(20260220, 1)[0]
    a = int(row[3])
    b = int(row[4])
    own = replace(reproduce.compute_torsion(a, b), torsion_type=torsion_type)
    reference = replace(
        reproduce.sage_reference(a, b),
        torsion_type=torsion_type,
        order=reference_order,
    )
    monkeypatch.setattr(reproduce, "compute_torsion", lambda _a, _b: own)
    monkeypatch.setattr(reproduce, "sage_reference", lambda _a, _b: reference)

    outcome, _payload = reproduce._evaluate_case(row)
    detail_codes = set(outcome["detail"].split(";"))

    assert outcome["match"] == "0"
    assert required_codes <= detail_codes


@pytest.mark.parametrize("generator_case", ["identity", "all_points", "wrong_exponent"])
def test_redundant_or_wrong_exponent_generators_are_rejected(
    monkeypatch,
    generator_case,
) -> None:
    reproduce = _load_reproduce_module()
    row = _expected_case_rows(20260220, 1)[1]
    a = int(row[3])
    b = int(row[4])
    own = reproduce.compute_torsion(a, b)
    reference = reproduce.sage_reference(a, b)

    if generator_case == "identity":
        identity = next(point for point in own.torsion_points if point.is_zero())
        own = replace(own, generators=[*own.generators, identity])
    elif generator_case == "all_points":
        own = replace(own, generators=list(own.torsion_points))
    elif generator_case == "wrong_exponent":
        monkeypatch.setattr(reproduce, "exact_order", lambda _point: 1)
    else:
        raise AssertionError(generator_case)

    monkeypatch.setattr(reproduce, "compute_torsion", lambda _a, _b: own)
    monkeypatch.setattr(reproduce, "sage_reference", lambda _a, _b: reference)
    outcome, _payload = reproduce._evaluate_case(row)

    assert outcome["match"] == "0"
    assert "generator_order" in outcome["detail"].split(";")


def test_canonical_case_file_is_exact_and_has_stable_fingerprints() -> None:
    assert CASES_PATH.is_file()
    expected_rows = _expected_case_rows(20260220, 10000)
    expected_bytes = _csv_bytes(CASE_HEADER, expected_rows)
    raw = CASES_PATH.read_bytes()

    assert raw == expected_bytes
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert hashlib.sha256(raw).hexdigest() == (
        "dd87d3f4933ed7fd89388c97c258f4b13c4946fb5a2108ac8125d1d70fac147b"
    )
    assert len(expected_rows) == 10015
    pairs = [(int(row[3]), int(row[4])) for row in expected_rows]
    assert len(set(pairs)) == 10015
    assert all(-16 * (4 * a**3 + 27 * b**2) != 0 for a, b in pairs)
    curated_pairs = set(pairs[:15])
    assert not curated_pairs.intersection(pairs[15:])
    assert sum(a == 0 for a, _b in pairs[15:]) == 2
    assert sum(b == 0 for _a, b in pairs[15:]) == 0
    random_payload = "".join(
        f"{row[3]},{row[4]}\n" for row in expected_rows[15:]
    ).encode("utf-8")
    assert hashlib.sha256(random_payload).hexdigest() == (
        "28c87949a5d0e0bac14e4cfed0e226d90bc4336a8fe82a5f1cd6fe958932180a"
    )


def test_canonical_result_has_exact_release_gates_and_fingerprints() -> None:
    assert RESULT_PATH.is_file()
    raw = RESULT_PATH.read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw
    header, rows = _read_result(RESULT_PATH)
    assert tuple(header) == RESULT_HEADER
    _assert_fixed_typed_schema(rows)
    summary_rows = [row for row in rows if row["record_type"] == "summary"]
    count_rows = [row for row in rows if row["record_type"] == "type_count"]
    mismatch_rows = [row for row in rows if row["record_type"] == "mismatch"]
    assert tuple(row["metric"] for row in summary_rows) == SUMMARY_METRICS
    assert [row["torsion_type"] for row in count_rows] == list(MAZUR_TYPES)
    assert len(count_rows) == 15
    assert [int(row["value"]) for row in count_rows] == [9995, 7] + [1] * 13
    assert mismatch_rows == []
    summary = _summary_values(rows)
    assert summary == {
        "status": "pass",
        "seed": "20260220",
        "a_min": "-10000",
        "a_max": "10000",
        "b_min": "-10000",
        "b_max": "10000",
        "zero_coefficient_policy": "allowed_if_nonsingular",
        "curated_case_count": "15",
        "random_case_count": "10000",
        "total_case_count": "10015",
        "unique_pair_count": "10015",
        "singular_inputs_in_cases": "0",
        "random_draw_attempts": "10000",
        "singular_redraw_count": "0",
        "curated_overlap_redraw_count": "0",
        "duplicate_random_redraw_count": "0",
        "total_redraw_count": "0",
        "random_a_zero_count": "2",
        "random_b_zero_count": "0",
        "random_any_zero_count": "2",
        "match_count": "10015",
        "mismatch_count": "0",
        "all_15_mazur_types_covered": "1",
        "cases_sha256": "dd87d3f4933ed7fd89388c97c258f4b13c4946fb5a2108ac8125d1d70fac147b",
        "random_pairs_sha256": "28c87949a5d0e0bac14e4cfed0e226d90bc4336a8fe82a5f1cd6fe958932180a",
        "outcomes_sha256": "cd2963a645144563c9c04641b57639a5ebcad6a5dd56cfe487f84ed67bdcb920",
        "max_seconds": "3600",
    }


def test_own_algorithm_sage_reference_boundary_is_unchanged() -> None:
    package_root = REPOSITORY_ROOT / "src" / "rational_torsion"
    source_by_name = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(package_root.glob("*.py"))
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
