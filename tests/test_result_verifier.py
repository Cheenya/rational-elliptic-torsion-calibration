from __future__ import annotations

import csv
from dataclasses import replace
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import socket
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_results.py"


def _load_verifier():
    specification = importlib.util.spec_from_file_location("verify_results", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def verifier():
    return _load_verifier()


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_small_tree(base: Path, *, sample_size: int = 1) -> dict[str, Path]:
    data = base / "data"
    results = base / "results"
    data.mkdir(parents=True)
    results.mkdir()
    paths = {
        "mazur_fixture": data / "mazur_representatives.csv",
        "mazur_result": results / "mazur_validation.csv",
        "grid_fixture": data / "coefficient_grid.csv",
        "grid_result": results / "grid_validation.csv",
        "cases": data / "calibration_cases.csv",
        "calibration_result": results / "calibration_summary.csv",
        "environment": results / "environment.json",
    }
    shutil.copy2(ROOT / "data" / "mazur_representatives.csv", paths["mazur_fixture"])
    shutil.copy2(ROOT / "results" / "mazur_validation.csv", paths["mazur_result"])
    shutil.copy2(ROOT / "data" / "coefficient_grid.csv", paths["grid_fixture"])
    shutil.copy2(ROOT / "results" / "grid_validation.csv", paths["grid_result"])

    generated = _run(
        [
            "sage",
            "-python",
            str(ROOT / "scripts" / "reproduce.py"),
            "--seed",
            "20260220",
            "--sample-size",
            str(sample_size),
            "--cases",
            str(paths["cases"]),
            "--generate-cases",
        ],
        cwd=ROOT,
    )
    assert generated.returncode == 0, generated.stderr
    reproduced = _run(
        [
            "sage",
            "-python",
            str(ROOT / "scripts" / "reproduce.py"),
            "--seed",
            "20260220",
            "--sample-size",
            str(sample_size),
            "--cases",
            str(paths["cases"]),
            "--output",
            str(paths["calibration_result"]),
            "--max-seconds",
            "3600",
        ],
        cwd=ROOT,
    )
    assert reproduced.returncode == 0, reproduced.stderr
    return paths


def _verifier_command(paths: dict[str, Path], *, sample_size: int = 1) -> list[str]:
    return [
        "sage",
        "-python",
        str(SCRIPT),
        "--mazur-fixture",
        str(paths["mazur_fixture"]),
        "--mazur-result",
        str(paths["mazur_result"]),
        "--grid-fixture",
        str(paths["grid_fixture"]),
        "--grid-result",
        str(paths["grid_result"]),
        "--calibration-cases",
        str(paths["cases"]),
        "--calibration-result",
        str(paths["calibration_result"]),
        "--environment-output",
        str(paths["environment"]),
        "--random-sample-size",
        str(sample_size),
        "--max-seconds",
        "3600",
    ]


def test_small_calibration_real_semantic_helpers_succeed_without_publication(
    verifier,
    tmp_path: Path,
) -> None:
    paths = _prepare_small_tree(tmp_path)
    mazur_rows = verifier._verify_mazur(
        paths["mazur_fixture"],
        paths["mazur_result"],
    )
    verifier._verify_grid(paths["grid_fixture"], paths["grid_result"])
    verifier._verify_calibration(
        paths["cases"],
        paths["calibration_result"],
        mazur_rows,
        random_sample_size=1,
        max_seconds=3600,
        allow_noncanonical_fail=True,
    )
    assert not paths["environment"].exists()


def test_public_small_fail_artifact_is_rejected_without_environment_or_pass(
    tmp_path: Path,
) -> None:
    paths = _prepare_small_tree(tmp_path)
    sentinel = b"prior environment\n"
    paths["environment"].write_bytes(sentinel)
    completed = _run(_verifier_command(paths), cwd=tmp_path)
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr.startswith("Verification error:")
    assert "Traceback" not in completed.stderr
    assert "Results verification: PASS" not in completed.stderr
    assert paths["environment"].read_bytes() == sentinel


CSV_FAMILIES = [
    ("mazur fixture", 4),
    ("mazur result", 15),
    ("grid fixture", 3),
    ("grid result", 12),
    ("calibration cases", 6),
    ("calibration result", 15),
]


def _csv_bytes(header: list[str], row: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(row)
    return stream.getvalue().encode("utf-8")


@pytest.mark.parametrize(("label", "width"), CSV_FAMILIES)
@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "empty",
        "non_utf8",
        "malformed",
        "crlf",
        "unterminated",
        "wrong_header",
        "short",
        "overlong",
    ],
)
def test_strict_csv_reader_rejects_all_shape_faults(
    verifier,
    tmp_path: Path,
    label: str,
    width: int,
    corruption: str,
) -> None:
    path = tmp_path / "input.csv"
    header = [f"field_{index}" for index in range(width)]
    payload = _csv_bytes(header, [""] * width)
    if corruption == "missing":
        pass
    elif corruption == "empty":
        path.write_bytes(b"")
    elif corruption == "non_utf8":
        path.write_bytes(b"\xff\n")
    elif corruption == "malformed":
        path.write_bytes(b'"unterminated\n')
    elif corruption == "crlf":
        path.write_bytes(payload.replace(b"\n", b"\r\n"))
    elif corruption == "unterminated":
        path.write_bytes(payload[:-1])
    elif corruption == "wrong_header":
        path.write_bytes(_csv_bytes(["wrong"] + header[1:], [""] * width))
    elif corruption == "short":
        path.write_bytes(_csv_bytes(header, [""] * (width - 1)))
    elif corruption == "overlong":
        path.write_bytes(_csv_bytes(header, [""] * (width + 1)))
    else:
        raise AssertionError(corruption)

    with pytest.raises(ValueError):
        verifier._read_csv_exact(path, label=label, header=header)


@pytest.mark.parametrize(
    "value",
    [True, False, 1.0, "1.0", "1e0", " 1", "1 ", "+1", "01", "-0", "", None],
)
def test_canonical_integer_rejects_noncanonical_values(verifier, value) -> None:
    with pytest.raises(ValueError):
        verifier._canonical_integer(value, label="integer")


@pytest.mark.parametrize(
    "value",
    [
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "g" * 64,
        " a" + "a" * 63,
        "",
        None,
        True,
    ],
)
def test_sha256_parser_rejects_noncanonical_values(verifier, value) -> None:
    with pytest.raises(ValueError):
        verifier._canonical_sha256(value, label="digest")


def _read_rows(verifier, path: Path, header: list[str]) -> list[list[str]]:
    _raw, rows = verifier._read_csv_exact(path, label=path.name, header=header)
    return rows


@pytest.mark.parametrize("column", [0, 1, 5, 6, 7, 9, 10, 11, 12, 13, 14])
def test_mazur_semantic_row_corruption_is_rejected(verifier, column: int) -> None:
    rows = _read_rows(verifier, ROOT / "results" / "mazur_validation.csv", verifier.MAZUR_RESULT_HEADER)
    expected = [row[:] for row in rows]
    rows[0][column] = "changed"
    with pytest.raises(ValueError, match="Mazur result row 1"):
        verifier._assert_rows_equal(rows, expected, label="Mazur result")


@pytest.mark.parametrize("mutation", ["duplicate", "reorder"])
def test_mazur_duplicate_or_reordered_row_is_rejected(verifier, mutation: str) -> None:
    rows = _read_rows(verifier, ROOT / "results" / "mazur_validation.csv", verifier.MAZUR_RESULT_HEADER)
    expected = [row[:] for row in rows]
    if mutation == "duplicate":
        rows[1] = rows[0][:]
    else:
        rows[0], rows[1] = rows[1], rows[0]
    with pytest.raises(ValueError):
        verifier._assert_rows_equal(rows, expected, label="Mazur result")


@pytest.mark.parametrize("column", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
def test_grid_semantic_row_corruption_is_rejected(verifier, column: int) -> None:
    rows = _read_rows(verifier, ROOT / "results" / "grid_validation.csv", verifier.GRID_RESULT_HEADER)
    expected = [row[:] for row in rows]
    rows[0][column] = "changed"
    with pytest.raises(ValueError, match="grid result row 1"):
        verifier._assert_rows_equal(rows, expected, label="grid result")


def test_grid_real_row_under_wrong_identifier_is_rejected(verifier) -> None:
    rows = _read_rows(verifier, ROOT / "results" / "grid_validation.csv", verifier.GRID_RESULT_HEADER)
    expected = [row[:] for row in rows]
    rows[0] = rows[1][:]
    rows[0][0] = expected[0][0]
    with pytest.raises(ValueError):
        verifier._assert_rows_equal(rows, expected, label="grid result")


def test_exact_seeded_regeneration_rejects_substitution_with_updated_file_hash(verifier) -> None:
    _raw, mazur_rows = verifier._load_mazur_fixture(ROOT / "data" / "mazur_representatives.csv")
    expected, _stats = verifier._regenerate_cases(mazur_rows, random_sample_size=2)
    changed = [row[:] for row in expected]
    changed[-1][3] = str(int(changed[-1][3]) + 1)
    payload = verifier._serialize_csv(verifier.CALIBRATION_CASE_HEADER, changed)
    assert len(verifier._sha256(payload)) == 64
    with pytest.raises(ValueError, match="calibration cases row"):
        verifier._assert_rows_equal(changed, expected, label="calibration cases")


@pytest.mark.parametrize(
    "mutation",
    [
        "redraw_count",
        "zero_count",
        "metric_reorder",
        "metric_duplicate",
        "metric_missing",
        "wrong_occupancy",
        "type_count_shift",
        "case_hash",
        "outcome_hash",
        "append_mismatch",
        "status",
    ],
)
def test_calibration_result_corruption_matrix(verifier, mutation: str) -> None:
    rows = _read_rows(
        verifier,
        ROOT / "results" / "calibration_summary.csv",
        verifier.CALIBRATION_RESULT_HEADER,
    )
    expected = [row[:] for row in rows]
    metric_index = {row[1]: index for index, row in enumerate(rows[:27])}
    if mutation == "redraw_count":
        rows[metric_index["random_draw_attempts"]][2] = "10001"
    elif mutation == "zero_count":
        rows[metric_index["random_a_zero_count"]][2] = "3"
    elif mutation == "metric_reorder":
        rows[0], rows[1] = rows[1], rows[0]
    elif mutation == "metric_duplicate":
        rows[1] = rows[0][:]
    elif mutation == "metric_missing":
        rows.pop(1)
    elif mutation == "wrong_occupancy":
        rows[0][3] = "Z/1"
    elif mutation == "type_count_shift":
        rows[27][2] = str(int(rows[27][2]) - 1)
        rows[28][2] = str(int(rows[28][2]) + 1)
    elif mutation == "case_hash":
        rows[metric_index["cases_sha256"]][2] = "0" * 64
    elif mutation == "outcome_hash":
        rows[metric_index["outcomes_sha256"]][2] = "0" * 64
    elif mutation == "append_mismatch":
        rows.append(
            [
                "mismatch", "", "", "", "random_00001", "random", "",
                "1", "1", "Z/1", "1", "Z/2", "2", "0", "torsion_type",
            ]
        )
    elif mutation == "status":
        rows[metric_index["status"]][2] = "fail"
    else:
        raise AssertionError(mutation)
    with pytest.raises(ValueError):
        verifier._assert_rows_equal(rows, expected, label="calibration result")


def _valid_environment() -> dict[str, object]:
    return {
        "os": "Darwin",
        "architecture": "arm64",
        "cpu_model": "Apple M1",
        "logical_cores": 8,
        "memory_gib": 8.0,
        "sage_version": "10.8",
        "python_version": "3.13.7",
        "compiler_version": "Apple clang version 21.0.0",
    }


def test_environment_accepts_exact_canonical_compiler_banner(verifier) -> None:
    environment = _valid_environment()
    environment["compiler_version"] = (
        "Apple clang version 21.0.0 (clang-2100.1.1.101)"
    )
    payload = verifier._environment_bytes(environment)
    assert b"clang-2100.1.1.101" in payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("os", ""),
        ("architecture", "arm\n64"),
        ("cpu_model", "/tmp/model"),
        ("logical_cores", True),
        ("logical_cores", 8.0),
        ("logical_cores", 0),
        ("memory_gib", 8),
        ("memory_gib", float("inf")),
        ("memory_gib", 0.0),
        ("sage_version", "10.7"),
        ("python_version", "3.13.6"),
        ("compiler_version", "clang\nsecond line"),
        ("compiler_version", "C:\\tool\\clang"),
    ],
)
def test_environment_schema_rejects_value_faults(verifier, field: str, value) -> None:
    environment = _valid_environment()
    environment[field] = value
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


def test_environment_schema_rejects_extra_and_missing_keys(verifier) -> None:
    extra = _valid_environment()
    extra["time" + "stamp"] = "2026-08-15"
    with pytest.raises(ValueError):
        verifier._environment_bytes(extra)
    missing = _valid_environment()
    missing.pop("architecture")
    with pytest.raises(ValueError):
        verifier._environment_bytes(missing)


def test_environment_schema_rejects_identity_like_value(verifier) -> None:
    environment = _valid_environment()
    environment["cpu_model"] = "user" + "name=someone"
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


def test_environment_publication_rolls_back_pre_replace_fault(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "environment.json"
    sentinel = b"previous\n"
    destination.write_bytes(sentinel)

    def fail_before(_source: Path, _destination: Path) -> None:
        raise OSError("injected pre-replace failure")

    monkeypatch.setattr(verifier, "_atomic_replace", fail_before)
    with pytest.raises(OSError):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert destination.read_bytes() == sentinel
    assert sorted(tmp_path.iterdir()) == [destination]


def test_environment_publication_rolls_back_post_mutation_fault(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "environment.json"
    sentinel = b"previous\n"
    destination.write_bytes(sentinel)

    def fail_after(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise OSError("injected post-mutation failure")

    monkeypatch.setattr(verifier, "_atomic_replace", fail_after)
    with pytest.raises(OSError):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert destination.read_bytes() == sentinel
    assert sorted(tmp_path.iterdir()) == [destination]


def test_environment_publication_removes_new_destination_after_mutation_fault(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "environment.json"

    def fail_after(source: Path, target: Path) -> None:
        os.replace(source, target)
        raise OSError("injected post-mutation failure")

    monkeypatch.setattr(verifier, "_atomic_replace", fail_after)
    with pytest.raises(OSError):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_environment_publication_restores_deleted_destination_after_commit_fault(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "environment.json"
    sentinel = b"previous\n"
    destination.write_bytes(sentinel)
    scientific = {}
    for name in (
        "mazur_validation.csv",
        "grid_validation.csv",
        "calibration_summary.csv",
    ):
        path = tmp_path / name
        path.write_bytes(f"{name}\n".encode())
        scientific[path] = path.read_bytes()

    def delete_then_fail(_source: Path, target: Path) -> None:
        target.unlink()
        raise OSError("injected deletion before commit failure")

    monkeypatch.setattr(verifier, "_atomic_replace", delete_then_fail)
    with pytest.raises(OSError, match="deletion before commit"):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert destination.read_bytes() == sentinel
    assert all(path.read_bytes() == payload for path, payload in scientific.items())
    assert not list(tmp_path.glob(".*.stage"))
    assert not list(tmp_path.glob(".*.recovery"))


def test_controlled_main_error_has_no_traceback_or_success_lines(
    verifier,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "_run_verification",
        lambda _arguments: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )
    assert verifier.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Verification error: injected failure\n"
    assert "Traceback" not in captured.err


def test_cooperative_timeout_reports_processed_count(verifier) -> None:
    rows = [["random_00001", "random", "", "1", "1", "random_seed_20260220"]]
    ticks = iter([0.0, 2.0])
    with pytest.raises(TimeoutError, match="processed 0 cases"):
        verifier._recompute_calibration(
            rows,
            max_seconds=1.0,
            clock=lambda: next(ticks),
            compute_fn=lambda _a, _b: None,
            reference_fn=lambda _a, _b: None,
        )


def test_injected_own_exception_is_controlled_by_main(
    verifier,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        verifier,
        "_run_verification",
        lambda _arguments: (_ for _ in ()).throw(ValueError("own computation failed")),
    )
    assert verifier.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Verification error: own computation failed")


def test_result_directory_inventory_rejects_unexpected_file(verifier, tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    for name in (
        "mazur_validation.csv",
        "grid_validation.csv",
        "calibration_summary.csv",
    ):
        (results / name).write_text("x\n", encoding="utf-8")
    verifier._check_result_inventory(results / "environment.json")
    (results / "extra.csv").write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected result file"):
        verifier._check_result_inventory(results / "environment.json")


def test_source_boundary_is_preserved(verifier) -> None:
    verifier._check_source_boundary(ROOT / "src" / "rational_torsion")
    own_files = ["model.py", "candidates.py", "group.py", "core.py"]
    marker = "torsion_" + "subgroup"
    order_marker = "torsion_" + "order"
    for name in own_files:
        text = (ROOT / "src" / "rational_torsion" / name).read_text(encoding="utf-8")
        assert marker not in text
        assert order_marker not in text
        assert "import .reference" not in text


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.write_text(stream.getvalue(), encoding="utf-8")


def _main_argv(paths: dict[str, Path], *, sample_size: int = 1) -> list[str]:
    return _verifier_command(paths, sample_size=sample_size)[3:]


def test_integrated_mazur_verifier_rejects_coordinated_result_edit(
    verifier,
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "mazur_representatives.csv"
    result = tmp_path / "mazur_validation.csv"
    shutil.copy2(ROOT / "data" / fixture.name, fixture)
    rows = _read_rows(verifier, ROOT / "results" / result.name, verifier.MAZUR_RESULT_HEADER)
    rows[0][1] = "2"
    rows[0][6] = "Z/2"
    rows[0][7] = "2"
    rows[0][8] = "2"
    rows[0][11] = "Z/2"
    rows[0][12] = "2"
    _write_csv(result, verifier.MAZUR_RESULT_HEADER, rows)
    with pytest.raises(ValueError, match="Mazur result row 1"):
        verifier._verify_mazur(fixture, result)


def test_integrated_grid_verifier_rejects_coordinated_result_edit(
    verifier,
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "coefficient_grid.csv"
    result = tmp_path / "grid_validation.csv"
    shutil.copy2(ROOT / "data" / fixture.name, fixture)
    rows = _read_rows(verifier, ROOT / "results" / result.name, verifier.GRID_RESULT_HEADER)
    rows[0][4] = "Z/2"
    rows[0][5] = "2"
    rows[0][8] = "Z/2"
    rows[0][9] = "2"
    _write_csv(result, verifier.GRID_RESULT_HEADER, rows)
    with pytest.raises(ValueError, match="grid result row 1"):
        verifier._verify_grid(fixture, result)


@pytest.mark.parametrize("mutation", ["identifier", "pair", "duplicate", "reorder"])
def test_integrated_grid_fixture_substitution_is_rejected(
    verifier,
    tmp_path: Path,
    mutation: str,
) -> None:
    rows = _read_rows(
        verifier,
        ROOT / "data" / "coefficient_grid.csv",
        verifier.GRID_FIXTURE_HEADER,
    )
    if mutation == "identifier":
        rows[0][0] = "curve_9999"
    elif mutation == "pair":
        rows[0][1] = "9"
    elif mutation == "duplicate":
        rows[1] = rows[0][:]
    elif mutation == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    path = tmp_path / "coefficient_grid.csv"
    _write_csv(path, verifier.GRID_FIXTURE_HEADER, rows)
    with pytest.raises(ValueError):
        verifier._load_grid_fixture(path)


def test_invalid_own_point_structure_reaches_integrated_evaluator(
    verifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = verifier.compute_torsion(-10, -10)
    invalid = replace(
        original,
        torsion_points=list(original.torsion_points) + [original.torsion_points[0]],
    )
    monkeypatch.setattr(verifier, "compute_torsion", lambda _a, _b: invalid)
    with pytest.raises(ValueError, match="duplicate own point"):
        verifier._evaluate_pair(-10, -10)


def test_invalid_generated_group_reaches_integrated_evaluator(
    verifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = verifier.compute_torsion(0, 1)
    invalid = replace(original, generators=[])
    monkeypatch.setattr(verifier, "compute_torsion", lambda _a, _b: invalid)
    with pytest.raises(ValueError, match="generator"):
        verifier._evaluate_pair(0, 1, expected_type="Z/6")


def test_integrated_calibration_verifier_rejects_coordinated_summary_edit(
    verifier,
    tmp_path: Path,
) -> None:
    paths = _prepare_small_tree(tmp_path)
    rows = _read_rows(
        verifier,
        paths["calibration_result"],
        verifier.CALIBRATION_RESULT_HEADER,
    )
    metric_index = {row[1]: index for index, row in enumerate(rows[:27])}
    rows[metric_index["match_count"]][2] = "15"
    rows[metric_index["total_case_count"]][2] = "15"
    _write_csv(paths["calibration_result"], verifier.CALIBRATION_RESULT_HEADER, rows)
    _raw, mazur_rows = verifier._load_mazur_fixture(paths["mazur_fixture"])
    with pytest.raises(ValueError, match="calibration result row"):
        verifier._verify_calibration(
            paths["cases"],
            paths["calibration_result"],
            mazur_rows,
            random_sample_size=1,
            max_seconds=3600,
            allow_noncanonical_fail=True,
        )


def test_known_seed_prefix_is_independent_and_exact(verifier) -> None:
    _raw, mazur_rows = verifier._load_mazur_fixture(
        ROOT / "data" / "mazur_representatives.csv"
    )
    rows, stats = verifier._regenerate_cases(mazur_rows, random_sample_size=5)
    assert rows[15:] == [
        ["random_00001", "random", "", "-4368", "-3664", "random_seed_20260220"],
        ["random_00002", "random", "", "8338", "428", "random_seed_20260220"],
        ["random_00003", "random", "", "-853", "-3080", "random_seed_20260220"],
        ["random_00004", "random", "", "2286", "-7767", "random_seed_20260220"],
        ["random_00005", "random", "", "8210", "11", "random_seed_20260220"],
    ]
    assert stats == {
        "random_draw_attempts": 5,
        "singular_redraw_count": 0,
        "curated_overlap_redraw_count": 0,
        "duplicate_random_redraw_count": 0,
        "random_a_zero_count": 0,
        "random_b_zero_count": 0,
        "random_any_zero_count": 0,
    }


def test_changed_seeded_case_with_recomputed_case_hash_and_counts_is_rejected(
    verifier,
    tmp_path: Path,
) -> None:
    paths = _prepare_small_tree(tmp_path)
    case_rows = _read_rows(
        verifier,
        paths["cases"],
        verifier.CALIBRATION_CASE_HEADER,
    )
    case_rows[-1][3] = str(int(case_rows[-1][3]) + 1)
    _write_csv(paths["cases"], verifier.CALIBRATION_CASE_HEADER, case_rows)
    changed_hash = hashlib.sha256(paths["cases"].read_bytes()).hexdigest()

    result_rows = _read_rows(
        verifier,
        paths["calibration_result"],
        verifier.CALIBRATION_RESULT_HEADER,
    )
    metric_index = {row[1]: index for index, row in enumerate(result_rows[:27])}
    result_rows[metric_index["cases_sha256"]][2] = changed_hash
    result_rows[metric_index["total_case_count"]][2] = "16"
    result_rows[metric_index["unique_pair_count"]][2] = "16"
    _write_csv(
        paths["calibration_result"],
        verifier.CALIBRATION_RESULT_HEADER,
        result_rows,
    )
    _raw, mazur_rows = verifier._load_mazur_fixture(paths["mazur_fixture"])
    with pytest.raises(ValueError, match="calibration cases row 16"):
        verifier._verify_calibration(
            paths["cases"],
            paths["calibration_result"],
            mazur_rows,
            random_sample_size=1,
            max_seconds=3600,
            allow_noncanonical_fail=True,
        )


@pytest.mark.parametrize("failure_side", ["own", "reference", "timeout"])
def test_public_main_fault_preserves_environment_and_scientific_files(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_side: str,
) -> None:
    paths = _prepare_small_tree(tmp_path)
    sentinel = b"previous environment\n"
    paths["environment"].write_bytes(sentinel)
    scientific = {
        name: paths[name].read_bytes()
        for name in ("mazur_result", "grid_result", "calibration_result")
    }
    if failure_side == "own":
        monkeypatch.setattr(
            verifier,
            "compute_torsion",
            lambda _a, _b: (_ for _ in ()).throw(RuntimeError("own injected")),
        )
    elif failure_side == "reference":
        monkeypatch.setattr(
            verifier,
            "sage_reference",
            lambda _a, _b: (_ for _ in ()).throw(RuntimeError("reference injected")),
        )
    else:
        monkeypatch.setattr(verifier, "_verify_mazur", lambda _a, _b: verifier.MAZUR_ROWS)
        monkeypatch.setattr(verifier, "_verify_grid", lambda _a, _b: None)
        monkeypatch.setattr(
            verifier,
            "_verify_calibration",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                TimeoutError("cooperative timeout after processed 3 cases")
            ),
        )
    assert verifier.main(_main_argv(paths)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Verification error:")
    assert "Traceback" not in captured.err
    assert paths["environment"].read_bytes() == sentinel
    assert all(paths[name].read_bytes() == payload for name, payload in scientific.items())
    assert not list(paths["environment"].parent.glob(".*.stage"))
    assert not list(paths["environment"].parent.glob(".*.recovery"))


@pytest.mark.parametrize(
    "value",
    [
        1,
        None,
        "x" * 201,
        "ﬃ" * 70,
        "control\x00value",
        "/" + "Users/example/model",
        "/" + "home/example/model",
        "host" + "name=value",
        "serial number 123",
        "time" + "stamp=2026",
        {"nested": "value"},
    ],
)
def test_environment_string_and_recursive_anonymity_faults(verifier, value) -> None:
    environment = _valid_environment()
    environment["cpu_model"] = value
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


@pytest.mark.parametrize("value", [float("nan"), 8.01])
def test_environment_memory_requires_finite_one_decimal(verifier, value: float) -> None:
    environment = _valid_environment()
    environment["memory_gib"] = value
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


def test_environment_rejects_local_account_name(verifier) -> None:
    local_name = Path.home().name
    assert local_name
    environment = _valid_environment()
    environment["cpu_model"] = f"processor for {local_name}"
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


@pytest.mark.parametrize(
    "value",
    [
        "relative/path",
        "embedded\\path",
        "relative／path",
        "relative＼path",
        "relative∕path",
        "relative⁄path",
        "relative⧵path",
        "prefix/segment/suffix",
        "file:%2Fusr%2Flocal%2Fbin%2Fclang",
        "processor@example",
        "Serial: ABC123",
        "serial-no: ABC123",
        "SN: ABC123",
        "serial-number=12345",
        "machine-id=abc123",
        "machine identifier: abc123",
        "device-id=abc123",
        "host-id=abc123",
        "home value",
        "cwd value",
        "path value",
        "os-user value",
        "login value",
        "account value",
        "550e8400-e29b-41d4-a716-446655440000",
        "01890f3e-7b2c-7abc-a123-0123456789ab",
        "00000000-0000-0000-0000-000000000000",
        "0123456789abcdef0123456789abcdef",
        "2026-08-15T12:34:56Z",
        "2026-08-15",
        "2026-8-5",
        "15-08-2026",
        "20260815T123456Z",
        "Sat, 15 Aug 2026 12:34:56 GMT",
        "15 Aug 2026 12:34:56 GMT",
        "1786797296",
        "1786797296000000",
        "1786797296000000000",
        "UTC+03:00",
        "00:1A:2B:3C:4D:5E",
        "001a.2b3c.4d5e",
        "192.168.1.42",
        "2001:db8::1",
        "ｓｅｒｉａｌ－ｎｕｍｂｅｒ=12345",
    ],
)
def test_environment_rejects_path_and_normalized_identity_patterns(
    verifier,
    value: str,
) -> None:
    environment = _valid_environment()
    environment["cpu_model"] = value
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


@pytest.mark.parametrize(
    "separator",
    ["\u0085", "\u2060", "\ud800", "\ue000", "\u0378", "\u2028", "\u2029"],
)
def test_environment_rejects_unicode_controls_and_separators(
    verifier,
    separator: str,
) -> None:
    environment = _valid_environment()
    environment["cpu_model"] = f"Apple{separator}M1"
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


def test_environment_rejects_actual_host_value(verifier) -> None:
    host_value = getattr(socket, "get" + "host" + "name")()
    assert host_value
    environment = _valid_environment()
    environment["cpu_model"] = f"processor on {host_value}"
    with pytest.raises(ValueError):
        verifier._environment_bytes(environment)


def test_recursive_identity_scan_rejects_nested_key_and_value(verifier) -> None:
    nested = {
        "safe": [
            {"serial-number": "550e8400-e29b-41d4-a716-446655440000"}
        ]
    }
    with pytest.raises(ValueError):
        verifier._reject_identity_content(nested, label="nested")


@pytest.mark.parametrize(
    "fragment",
    ["home", "cwd", "path", "os-user", "login", "account"],
)
def test_recursive_identity_scan_rejects_location_and_account_keys(
    verifier,
    fragment: str,
) -> None:
    with pytest.raises(ValueError):
        verifier._reject_identity_content({fragment: "safe"}, label="nested")


@pytest.mark.parametrize("phase", ["staging", "write", "flush", "close"])
def test_environment_stage_faults_preserve_all_prior_bytes(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    destination = tmp_path / "environment.json"
    sentinel = b"prior\n"
    destination.write_bytes(sentinel)
    scientific = {}
    for name in (
        "mazur_validation.csv",
        "grid_validation.csv",
        "calibration_summary.csv",
    ):
        path = tmp_path / name
        path.write_bytes(f"{name}\n".encode())
        scientific[path] = path.read_bytes()

    monkeypatch.setattr(
        verifier,
        "_write_staged",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(f"{phase} fault")),
    )
    with pytest.raises(OSError, match=phase):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert destination.read_bytes() == sentinel
    assert all(path.read_bytes() == payload for path, payload in scientific.items())
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [destination.name] + [path.name for path in scientific]
    )


def test_real_fsync_fault_removes_created_stage_and_preserves_bytes(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "environment.json"
    sentinel = b"prior\n"
    destination.write_bytes(sentinel)
    scientific = {}
    for name in (
        "mazur_validation.csv",
        "grid_validation.csv",
        "calibration_summary.csv",
    ):
        path = tmp_path / name
        path.write_bytes(f"{name}\n".encode())
        scientific[path] = path.read_bytes()

    monkeypatch.setattr(
        verifier.os,
        "fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("fsync injected")),
    )
    with pytest.raises(OSError, match="fsync injected"):
        verifier._publish_environment_atomic(destination, b"new\n")
    assert destination.read_bytes() == sentinel
    assert all(path.read_bytes() == payload for path, payload in scientific.items())
    assert not list(tmp_path.glob(".*.stage"))


def test_public_serialization_fault_preserves_environment(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _prepare_small_tree(tmp_path)
    sentinel = b"prior environment\n"
    paths["environment"].write_bytes(sentinel)
    monkeypatch.setattr(verifier, "_verify_mazur", lambda _a, _b: verifier.MAZUR_ROWS)
    monkeypatch.setattr(verifier, "_verify_grid", lambda _a, _b: None)
    monkeypatch.setattr(verifier, "_verify_calibration", lambda *_a, **_kw: None)
    invalid = _valid_environment()
    invalid["memory_gib"] = float("nan")
    monkeypatch.setattr(verifier, "_capture_environment", lambda: invalid)
    assert verifier.main(_main_argv(paths)) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Verification error:")
    assert paths["environment"].read_bytes() == sentinel


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--random-sample-size", "0"),
        ("--random-sample-size", "10001"),
        ("--max-seconds", "0"),
        ("--max-seconds", "nan"),
        ("--max-seconds", "inf"),
    ],
)
def test_cli_bounds_fail_before_any_publication(
    verifier,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    assert verifier.main([option, value]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Verification error:")


@pytest.mark.parametrize(
    ("source", "header"),
    [
        (ROOT / "data" / "mazur_representatives.csv", "MAZUR_FIXTURE_HEADER"),
        (ROOT / "results" / "mazur_validation.csv", "MAZUR_RESULT_HEADER"),
        (ROOT / "data" / "coefficient_grid.csv", "GRID_FIXTURE_HEADER"),
        (ROOT / "results" / "grid_validation.csv", "GRID_RESULT_HEADER"),
        (ROOT / "data" / "calibration_cases.csv", "CALIBRATION_CASE_HEADER"),
        (ROOT / "results" / "calibration_summary.csv", "CALIBRATION_RESULT_HEADER"),
    ],
)
@pytest.mark.parametrize("mutation", ["wrong_header", "short", "overlong", "trailing_blank"])
def test_actual_schema_families_reject_structural_faults(
    verifier,
    tmp_path: Path,
    source: Path,
    header: str,
    mutation: str,
) -> None:
    expected_header = getattr(verifier, header)
    _raw, rows = verifier._read_csv_exact(source, label=source.name, header=expected_header)
    if mutation == "wrong_header":
        changed_header = ["wrong"] + expected_header[1:]
        payload = verifier._serialize_csv(changed_header, rows)
    elif mutation == "short":
        payload = verifier._serialize_csv(expected_header, [rows[0][:-1]])
    elif mutation == "overlong":
        payload = verifier._serialize_csv(expected_header, [rows[0] + ["extra"]])
    else:
        payload = source.read_bytes() + b"\n"
    path = tmp_path / source.name
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        verifier._read_csv_exact(path, label=source.name, header=expected_header)


def test_family_loaders_reject_extra_record_and_reordered_rows(
    verifier,
    tmp_path: Path,
) -> None:
    mazur_rows = _read_rows(
        verifier,
        ROOT / "data" / "mazur_representatives.csv",
        verifier.MAZUR_FIXTURE_HEADER,
    )
    extra = tmp_path / "extra.csv"
    _write_csv(extra, verifier.MAZUR_FIXTURE_HEADER, mazur_rows + [mazur_rows[0]])
    with pytest.raises(ValueError, match="15 rows"):
        verifier._load_mazur_fixture(extra)
    reordered = tmp_path / "reordered.csv"
    mazur_rows[0], mazur_rows[1] = mazur_rows[1], mazur_rows[0]
    _write_csv(reordered, verifier.MAZUR_FIXTURE_HEADER, mazur_rows)
    with pytest.raises(ValueError, match="Mazur fixture row 1"):
        verifier._load_mazur_fixture(reordered)


def test_result_inventory_rejects_missing_file(verifier, tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    for name in ("mazur_validation.csv", "grid_validation.csv"):
        (results / name).write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required result file"):
        verifier._check_result_inventory(results / "environment.json")


@pytest.mark.parametrize("mutation", ["own_import", "second_oracle", "order_oracle"])
def test_source_boundary_rejects_each_forbidden_mutation(
    verifier,
    tmp_path: Path,
    mutation: str,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    if mutation == "own_import":
        with (source / "core.py").open("a", encoding="utf-8") as handle:
            handle.write("\nfrom .reference import sage_reference\n")
    elif mutation == "second_oracle":
        with (source / "core.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# " + "torsion_" + "subgroup\n")
    else:
        with (source / "core.py").open("a", encoding="utf-8") as handle:
            handle.write("\n# " + "torsion_" + "order\n")
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


def test_verifier_boundary_rejects_direct_oracle_call(verifier, tmp_path: Path) -> None:
    script = tmp_path / "verify_results.py"
    marker = "torsion_" + "subgroup"
    script.write_text(f"curve.{marker}()\n", encoding="utf-8")
    with pytest.raises(ValueError, match="direct Sage oracle"):
        verifier._check_verifier_boundary(script)


def test_verifier_boundary_rejects_private_reference_import(verifier, tmp_path: Path) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text("import rational_torsion.reference\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private reference module"):
        verifier._check_verifier_boundary(script)


@pytest.mark.parametrize(
    "statement",
    [
        "import reference",
        "import rational_torsion.reference",
        "from rational_torsion.reference import sage_reference",
        "from rational_torsion import reference",
        "from . import reference",
    ],
)
def test_verifier_boundary_rejects_all_private_reference_import_forms(
    verifier,
    tmp_path: Path,
    statement: str,
) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text(statement + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private reference module"):
        verifier._check_verifier_boundary(script)


@pytest.mark.parametrize(
    "source_text",
    [
        "probe = curve." + "torsion_" + "subgroup\n",
        "probe = curve." + "torsion_" + "order\n",
        "getattr(curve, " + repr("torsion_" + "subgroup") + ")\n",
        "getattr(curve, " + repr("torsion_" + "order") + ")\n",
        "__import__('rational_torsion.reference')\n",
        "importlib.import_module('rational_torsion.reference')\n",
        "from importlib import import_module as load\n"
        "load('rational_torsion.reference')\n",
        "name = " + repr("torsion_" + "subgroup") + "\n"
        "getattr(curve, name)()\n",
        "import rational_torsion as rt\n"
        "rt.reference.sage_reference(1, 1)\n",
        "curve.__getattribute__('torsion_' + 'subgroup')()\n",
        "from operator import attrgetter as pick\n"
        "pick('torsion_' + 'subgroup')(curve)()\n",
        "from operator import methodcaller as call\n"
        "call('torsion_' + 'subgroup')(curve)\n",
        "import rational_torsion as rt\n"
        "vars(rt)['sage_' + 'reference'](1, 1)\n",
        "import rational_torsion as rt\n"
        "rt.__dict__['sage_' + 'reference'](1, 1)\n",
        "globals()['oracle'](1, 1)\n",
        "locals()['oracle'](1, 1)\n",
        "dir(curve)\n",
        "delattr(curve, 'torsion_' + 'subgroup')\n",
    ],
)
def test_verifier_boundary_rejects_attribute_alias_and_dynamic_forms(
    verifier,
    tmp_path: Path,
    source_text: str,
) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text(source_text, encoding="utf-8")
    with pytest.raises(ValueError):
        verifier._check_verifier_boundary(script)


def test_source_boundary_recurses_into_nested_python(verifier, tmp_path: Path) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    nested = source / "nested"
    nested.mkdir()
    marker = "torsion_" + "subgroup"
    (nested / "extra.py").write_text(f"probe = curve.{marker}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


def test_source_boundary_rejects_public_reference_import_in_nested_init(
    verifier,
    tmp_path: Path,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    nested = source / "nested"
    nested.mkdir()
    (nested / "__init__.py").write_text(
        "from rational_torsion import sage_reference\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


@pytest.mark.parametrize(
    "source_text",
    [
        "from rational_torsion import sage_reference\n",
        "from rational_torsion import compare_with_sage\n",
        "from rational_torsion import sage_reference as oracle\n",
        "from rational_torsion import *\n",
        "import rational_torsion\nrational_torsion.sage_reference(1, 1)\n",
        "import rational_torsion\nrational_torsion.compare_with_sage(1, 1)\n",
    ],
)
def test_source_boundary_rejects_public_reference_api_outside_root_init(
    verifier,
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    nested = source / "nested"
    nested.mkdir()
    (nested / "extra.py").write_text(source_text, encoding="utf-8")
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


@pytest.mark.parametrize(
    "statement",
    [
        "import rational_torsion.reference.tools",
        "import rational_torsion.Reference",
        "from rational_torsion.reference.tools import sage_reference",
    ],
)
def test_verifier_boundary_rejects_reference_as_any_dotted_component(
    verifier,
    tmp_path: Path,
    statement: str,
) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text(statement + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="private reference module"):
        verifier._check_verifier_boundary(script)


def test_source_boundary_rejects_nonexact_root_reference_reexport(
    verifier,
    tmp_path: Path,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    with (source / "__init__.py").open("a", encoding="utf-8") as handle:
        handle.write("\nfrom .reference import sage_reference as oracle\n")
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


@pytest.mark.parametrize("mutation", ["extra", "missing", "hash_drift"])
def test_source_boundary_requires_exact_reviewed_inventory_and_hashes(
    verifier,
    tmp_path: Path,
    mutation: str,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    if mutation == "extra":
        (source / "benign.py").write_text("SAFE = 1\n", encoding="utf-8")
    elif mutation == "missing":
        (source / "candidates.py").unlink()
    else:
        with (source / "core.py").open("a", encoding="utf-8") as handle:
            handle.write("\nSAFE = 1\n")
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


@pytest.mark.parametrize("mutation", ["alias", "all_list"])
def test_source_boundary_rejects_root_init_semantic_drift(
    verifier,
    tmp_path: Path,
    mutation: str,
) -> None:
    source = tmp_path / "rational_torsion"
    shutil.copytree(ROOT / "src" / "rational_torsion", source)
    init_path = source / "__init__.py"
    if mutation == "alias":
        with init_path.open("a", encoding="utf-8") as handle:
            handle.write("\noracle = sage_reference\n")
    else:
        text = init_path.read_text(encoding="utf-8")
        init_path.write_text(
            text.replace('    "compare_with_sage",\n', ""),
            encoding="utf-8",
        )
    with pytest.raises(ValueError):
        verifier._check_source_boundary(source)


def test_verifier_boundary_rejects_casefolded_reference_member(
    verifier,
    tmp_path: Path,
) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text(
        "from rational_torsion import Reference\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="private reference module"):
        verifier._check_verifier_boundary(script)


def test_verifier_boundary_allows_public_reference_api_import(
    verifier,
    tmp_path: Path,
) -> None:
    script = tmp_path / "verify_results.py"
    script.write_text(
        "from rational_torsion import sage_reference\n",
        encoding="utf-8",
    )
    verifier._check_verifier_boundary(script)


def test_default_paths_are_rooted_outside_caller_directory(
    verifier,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    arguments = verifier._argument_parser().parse_args([])
    assert arguments.mazur_fixture == ROOT / "data" / "mazur_representatives.csv"
    assert arguments.mazur_result == ROOT / "results" / "mazur_validation.csv"
    assert arguments.grid_fixture == ROOT / "data" / "coefficient_grid.csv"
    assert arguments.grid_result == ROOT / "results" / "grid_validation.csv"
    assert arguments.calibration_cases == ROOT / "data" / "calibration_cases.csv"
    assert arguments.calibration_result == ROOT / "results" / "calibration_summary.csv"
    assert arguments.environment_output == ROOT / "results" / "environment.json"


def test_public_subprocess_uses_defaults_from_foreign_directory(tmp_path: Path) -> None:
    environment_path = ROOT / "results" / "environment.json"
    before = environment_path.read_bytes()
    completed = _run(["sage", "-python", str(SCRIPT)], cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert completed.stdout == (
        "Mazur: 15/15 semantically verified\n"
        "Grid: 438/438 semantically verified\n"
        "Calibration: 10015/10015 semantically verified, 0 mismatches\n"
        "Environment: 8 anonymized fields recorded\n"
        "Results verification: PASS\n"
    )
    assert environment_path.read_bytes() == before
