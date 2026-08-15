from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
TITLE = (
    "Вычисление групп кручения рациональных эллиптических кривых "
    "методом предварительной калибровки"
)
METADATA_FILES = (
    "README.md",
    "LICENSE-CODE",
    "LICENSE-DATA",
    "CITATION.cff",
    "pyproject.toml",
    "environment.yml",
    ".gitignore",
)
AUTHORS = [
    ("Чистяков", "Никита Андреевич"),
    ("Адамова", "Раиса Сергеевна"),
]


def _load_yaml(name: str) -> object:
    completed = subprocess.run(
        [
            "sage",
            "-python",
            "-c",
            (
                "import json, pathlib, sys, yaml; "
                "value = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); "
                "print(json.dumps(value, ensure_ascii=False))"
            ),
            str(ROOT / name),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _author_names(authors: object) -> list[tuple[str, str]]:
    assert isinstance(authors, list)
    return [
        (author["family-names"], author["given-names"])
        for author in authors
    ]


def test_required_repository_metadata_files_exist() -> None:
    missing = [name for name in METADATA_FILES if not (ROOT / name).is_file()]
    assert missing == []


def test_citation_metadata_has_exact_identity_and_factual_sources() -> None:
    citation = _load_yaml("CITATION.cff")
    assert isinstance(citation, dict)
    assert citation["cff-version"] == "1.2.0"
    assert citation["message"] == (
        "Пожалуйста, цитируйте это программное обеспечение и "
        "соответствующий доклад."
    )
    assert citation["type"] == "software"
    assert citation["title"] == TITLE
    assert citation["version"] == "0.1.0"
    assert citation["date-released"] == "2026-08-15"
    assert citation["license"] == "MIT"
    assert _author_names(citation["authors"]) == AUTHORS

    preferred = citation["preferred-citation"]
    assert preferred == {
        "type": "generic",
        "title": TITLE,
        "year": 2026,
        "authors": [
            {"family-names": family, "given-names": given}
            for family, given in AUTHORS
        ],
    }

    references = citation["references"]
    assert [reference["title"] for reference in references] == [
        "Вычисление группы точек конечного порядка рациональной эллиптической кривой",
        "Sur l'équation y^2 = x^3 - Ax - B dans les corps p-adiques",
        "Solution de quelques problèmes dans la théorie arithmétique des cubiques planes du premier genre",
        "Modular curves and the Eisenstein ideal",
        "Algorithms for Modular Elliptic Curves",
        "SageMath",
    ]
    adamova, lutz, nagell, mazur, cremona, sage = references
    assert adamova == {
        "type": "generic",
        "title": references[0]["title"],
        "authors": [{"family-names": "Adamova", "given-names": "R. S."}],
        "year": 2025,
        "isbn": "978-5-6054088-7-1",
    }
    assert lutz["authors"] == [
        {"family-names": "Lutz", "given-names": "Élisabeth"}
    ]
    assert lutz["year"] == 1937
    assert lutz["doi"] == "10.1515/crll.1937.177.238"
    assert nagell["authors"] == [
        {"family-names": "Nagell", "given-names": "Trygve"}
    ]
    assert nagell["year"] == 1935
    assert "doi" not in nagell
    assert mazur["authors"] == [
        {"family-names": "Mazur", "given-names": "Barry"}
    ]
    assert mazur["year"] == 1977
    assert mazur["doi"] == "10.1007/BF02684339"
    assert cremona["authors"] == [
        {"family-names": "Cremona", "given-names": "J. E."}
    ]
    assert cremona["edition"] == "Second edition"
    assert cremona["publisher"] == {"name": "Cambridge University Press"}
    assert cremona["year"] == 1997
    assert not {"doi", "url", "start", "end", "pages"}.intersection(cremona)
    assert sage["authors"] == [{"name": "The Sage Developers"}]
    assert sage["version"] == "10.8"
    assert sage["url"] == "https://www.sagemath.org"
    assert sage["doi"] == "10.5281/zenodo.8042260"


def test_environment_pins_reviewed_sage_runtime_and_packaging_tools() -> None:
    environment = _load_yaml("environment.yml")
    assert environment == {
        "name": "rational-elliptic-torsion-calibration",
        "channels": ["conda-forge"],
        "dependencies": [
            "python=3.13",
            "sage=10.8",
            "pytest=8.3",
            "pip",
            "setuptools>=68",
            "wheel",
        ],
    }


def test_pyproject_has_minimal_src_layout_contract() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata == {
        "build-system": {
            "requires": ["setuptools>=68"],
            "build-backend": "setuptools.build_meta",
        },
        "project": {
            "name": "rational-elliptic-torsion-calibration",
            "version": "0.1.0",
            "description": (
                "Exact rational elliptic-curve torsion computation with "
                "SageMath reference calibration"
            ),
            "requires-python": ">=3.13",
        },
        "tool": {
            "pytest": {"ini_options": {"pythonpath": ["src"]}},
            "setuptools": {"packages": {"find": {"where": ["src"]}}},
        },
    }


def test_readme_states_scope_boundary_commands_results_and_limits() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(f"# {TITLE}\n")
    for required in (
        "E_(a,b): y^2 = x^3 + ax + b",
        "Q",
        "a,b in Z",
        "4a^3 + 27b^2 != 0",
        "built-in Python `int`",
        "compute_torsion()",
        "src/rational_torsion/core.py",
        "sage_reference()",
        "src/rational_torsion/reference.py",
        "torsion_subgroup()",
        "torsion_order()",
        "SageMath 10.8",
        "conda env create -f environment.yml",
        "conda activate rational-elliptic-torsion-calibration",
        "sage -python -m pip install --no-deps -e .",
        "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src sage -python -m pytest -p no:cacheprovider -q",
        "sage -python -m compileall -q src scripts tests",
        "PYTHONPATH=src sage -python scripts/validate_mazur.py",
        "PYTHONPATH=src sage -python scripts/validate_grid.py",
        "PYTHONPATH=src sage -python scripts/reproduce.py",
        "--seed 20260220",
        "--sample-size 10000",
        "--cases data/calibration_cases.csv",
        "--max-seconds 3600",
        "PYTHONPATH=src sage -python scripts/verify_results.py",
        "results/mazur_validation.csv",
        "results/grid_validation.csv",
        "results/calibration_summary.csv",
        "results/environment.json",
        "15/15",
        "438/438",
        "10,015/10,015",
        "3-кручение",
        "все 15 типов Мазура",
        "ноль расхождений",
        "Cremona_66c1_short_model",
        "Cremona_15a1_short_model",
        "Cremona_210e2_short_model",
        "66c1",
        "15a1",
        "210e2",
        "для них не утверждается, что они являются глобальными минимальными моделями",
        "не являются доказательством универсальной корректности",
        "не являются оценкой распространённости",
        "не следует интерпретировать как естественное распределение",
        "Знак, порядок и базис образующих",
        "полную подгруппу",
        "не объявляются базисом Sage",
        "или инвариантным базисом",
        "факторизацию дискриминанта",
        "операционный потолок, а не бенчмарк",
        "CITATION.cff",
        "MIT",
        "CC BY 4.0",
    ):
        assert required in readme


def test_readme_uses_consistent_russian_technical_terms() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "exact-алгоритм" not in readme
    assert "provenance-метками" not in readme


def test_license_split_uses_exact_identifiers_and_canonical_terms() -> None:
    code_license = (ROOT / "LICENSE-CODE").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in code_license
    assert "Copyright (c) 2026 Nikita Chistyakov" in code_license
    assert "Permission is hereby granted, free of charge" in code_license
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in code_license

    data_license = (ROOT / "LICENSE-DATA").read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: CC-BY-4.0" in data_license
    assert "Nikita Chistyakov and Raisa Adamova" in data_license
    assert "data/" in data_license
    assert "results/" in data_license
    assert "https://creativecommons.org/licenses/by/4.0/legalcode" in data_license


@pytest.mark.parametrize(
    "path",
    (
        ".pytest_cache/state",
        ".mypy_cache/state",
        ".ruff_cache/state",
        ".hypothesis/examples/state",
        ".tox/state",
        ".nox/state",
        ".coverage",
        "htmlcov/index.html",
        "src/rational_torsion/__pycache__/core.cpython-313.pyc",
        "src/rational_torsion/core.pyc",
        ".venv/bin/python",
        "venv/bin/python",
        "env/bin/python",
        "build/lib/rational_torsion/core.py",
        "dist/rational_elliptic_torsion_calibration-0.1.0-py3-none-any.whl",
        "rational_elliptic_torsion_calibration.egg-info/PKG-INFO",
        "output/candidate.csv",
        ".DS_Store",
        "Thumbs.db",
    ),
)
def test_gitignore_ignores_generated_artifacts(path: str) -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 0


@pytest.mark.parametrize(
    "path",
    (
        "src/rational_torsion/core.py",
        "scripts/reproduce.py",
        "tests/test_calibration.py",
        "data/calibration_cases.csv",
        "results/calibration_summary.csv",
        "README.md",
        "CITATION.cff",
        "LICENSE-CODE",
        "LICENSE-DATA",
        "environment.yml",
        "pyproject.toml",
        "MANIFEST.sha256",
    ),
)
def test_gitignore_keeps_research_and_metadata_files(path: str) -> None:
    completed = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 1


def test_public_metadata_has_no_placeholders_contacts_or_false_claims() -> None:
    citation = _load_yaml("CITATION.cff")
    assert isinstance(citation, dict)
    assert not {
        "contact",
        "doi",
        "email",
        "repository",
        "repository-artifact",
        "repository-code",
        "url",
    }.intersection(citation)
    assert not {
        "affiliation",
        "doi",
        "email",
        "orcid",
        "repository",
        "repository-artifact",
        "repository-code",
        "url",
    }.intersection(citation["preferred-citation"])

    combined = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in METADATA_FILES
    )
    lowered = combined.lower()
    for forbidden in (
        "placeholder",
        "todo",
        "tbd",
        "sage-independent",
        "pure python",
        "standalone ordinary-python",
    ):
        assert forbidden not in lowered
    assert re.search(r"/(?:Users|home)/[^/\s]+", combined, flags=re.IGNORECASE) is None
    assert re.search(r"[A-Z]:\\", combined) is None
    assert re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", combined) is None
    scheme = "https" + "://"
    assert set(re.findall(rf"{scheme}[^\s\"']+", combined)) == {
        "https://creativecommons.org/licenses/by/4.0/legalcode",
        "https://www.sagemath.org",
    }
