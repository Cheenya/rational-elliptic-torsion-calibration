from __future__ import annotations

import dataclasses
import importlib
import inspect
from pathlib import Path

import pytest
from sage.all import QQ


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "rational_torsion"
OWN_MODULES = ("model.py", "candidates.py", "group.py", "core.py")


def _public_api():
    return importlib.import_module("rational_torsion")


def _assert_binary_int_signature(function, return_type: str) -> None:
    signature = inspect.signature(function)
    assert tuple(signature.parameters) == ("a", "b")
    for parameter in signature.parameters.values():
        assert parameter.annotation in (int, "int")
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.return_annotation in (return_type, getattr(_public_api(), return_type))


def test_public_api_has_exact_models_entrypoints_and_signatures():
    api = _public_api()

    assert api.__all__ == [
        "TorsionResult",
        "ReferenceResult",
        "ComparisonResult",
        "compute_torsion",
        "sage_reference",
        "compare_with_sage",
    ]
    assert [field.name for field in dataclasses.fields(api.TorsionResult)] == [
        "a",
        "b",
        "discriminant",
        "torsion_type",
        "generators",
        "torsion_points",
        "decision_log",
        "branch_hits",
    ]
    assert [field.name for field in dataclasses.fields(api.ReferenceResult)] == [
        "torsion_type",
        "order",
        "generators",
    ]
    assert [field.name for field in dataclasses.fields(api.ComparisonResult)] == [
        "ours",
        "reference",
        "match",
    ]
    _assert_binary_int_signature(api.compute_torsion, "TorsionResult")
    _assert_binary_int_signature(api.sage_reference, "ReferenceResult")
    _assert_binary_int_signature(api.compare_with_sage, "ComparisonResult")


def test_fixed_nonsingular_curve_matches_exact_reference():
    api = _public_api()

    ours = api.compute_torsion(0, 1)
    reference = api.sage_reference(0, 1)
    comparison = api.compare_with_sage(0, 1)

    assert ours.torsion_type == "Z/6"
    assert len(ours.torsion_points) == 6
    assert reference.torsion_type == "Z/6"
    assert reference.order == 6
    assert comparison.ours.torsion_type == ours.torsion_type
    assert comparison.reference.torsion_type == reference.torsion_type
    assert comparison.match is True


def test_comparison_match_checks_type_and_order(monkeypatch):
    api = _public_api()
    reference_module = importlib.import_module("rational_torsion.reference")
    ours = api.TorsionResult(
        a=-10,
        b=-10,
        discriminant=20800,
        torsion_type="Z/1",
        generators=[],
        torsion_points=[object()],
        decision_log=[],
        branch_hits={},
    )
    wrong_order = api.ReferenceResult(
        torsion_type="Z/1",
        order=2,
        generators=[],
    )

    monkeypatch.setattr(reference_module, "compute_torsion", lambda a, b: ours)
    monkeypatch.setattr(reference_module, "sage_reference", lambda a, b: wrong_order)

    assert reference_module.compare_with_sage(-10, -10).match is False

    wrong_type = api.ReferenceResult(
        torsion_type="Z/2",
        order=1,
        generators=[],
    )
    monkeypatch.setattr(reference_module, "sage_reference", lambda a, b: wrong_type)

    assert reference_module.compare_with_sage(-10, -10).match is False


@pytest.mark.parametrize("entrypoint_name", ["compute_torsion", "sage_reference"])
def test_singular_curve_is_rejected(entrypoint_name):
    entrypoint = getattr(_public_api(), entrypoint_name)

    with pytest.raises(ValueError, match="Singular curve"):
        entrypoint(0, 0)


def test_sage_oracle_is_confined_to_reference_module():
    source_by_name = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE_ROOT.glob("*.py"))
    }

    assert set(source_by_name) == {
        "__init__.py",
        "model.py",
        "candidates.py",
        "group.py",
        "core.py",
        "reference.py",
    }
    assert "torsion_subgroup" in source_by_name["reference.py"]
    assert all(
        "torsion_subgroup" not in source_by_name[module_name]
        for module_name in OWN_MODULES
    )
    assert all("torsion_order" not in source for source in source_by_name.values())
    assert all(
        "import reference" not in source_by_name[module_name]
        and "from .reference" not in source_by_name[module_name]
        for module_name in OWN_MODULES
    )


def _point_projection(point) -> tuple[str, ...]:
    if point.is_zero():
        return ("identity",)
    return ("point", str(QQ(point[0])), str(QQ(point[1])))


def _result_projection(result) -> tuple:
    return (
        result.a,
        result.b,
        result.discriminant,
        result.torsion_type,
        tuple(_point_projection(point) for point in result.generators),
        tuple(_point_projection(point) for point in result.torsion_points),
        tuple(result.decision_log),
        tuple(result.branch_hits.items()),
    )


@pytest.mark.parametrize(
    ("a", "b", "expected_type", "expected_point_count"),
    [
        pytest.param(0, 1, "Z/6", 6, id="a-zero-z6"),
        pytest.param(-9, 0, "Z/2 x Z/2", 4, id="b-zero-z2xz2"),
        pytest.param(0, -27648, "Z/3", 3, id="a-zero-cubic-z3"),
    ],
)
def test_own_algorithm_boundary_contract_is_exact_and_deterministic(
    a,
    b,
    expected_type,
    expected_point_count,
):
    api = _public_api()
    exact_order = importlib.import_module("rational_torsion.group").exact_order

    result = api.compute_torsion(a, b)
    repeated_result = api.compute_torsion(a, b)
    expected_discriminant = -16 * (4 * a**3 + 27 * b**2)

    assert result.a == a
    assert result.b == b
    assert expected_discriminant != 0
    assert result.discriminant == expected_discriminant
    assert result.torsion_type == expected_type
    assert len(result.torsion_points) == expected_point_count
    assert len(set(result.torsion_points)) == expected_point_count

    identity = result.torsion_points[0].curve()(0)
    assert identity in result.torsion_points
    for point in result.torsion_points:
        point_order = exact_order(point, max_order=12)
        assert isinstance(point_order, int)
        assert 1 <= point_order <= 12
        assert expected_point_count % point_order == 0

    assert all(generator in result.torsion_points for generator in result.generators)
    assert _result_projection(repeated_result) == _result_projection(result)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        pytest.param(-3, 2, id="positive-b"),
        pytest.param(-3, -2, id="negative-b"),
    ],
)
def test_nonzero_coefficient_singular_curves_are_rejected(a, b):
    assert -16 * (4 * a**3 + 27 * b**2) == 0

    with pytest.raises(ValueError, match="Singular curve"):
        _public_api().compute_torsion(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        pytest.param(True, 1, id="bool-a"),
        pytest.param(1.0, 1, id="float-a"),
        pytest.param("1", 1, id="string-a"),
        pytest.param(None, 1, id="none-a"),
        pytest.param(QQ(1) / 2, 1, id="rational-noninteger-a"),
        pytest.param(0, 1.0, id="float-b"),
    ],
)
@pytest.mark.parametrize(
    "entrypoint_name",
    ["compute_torsion", "sage_reference", "compare_with_sage"],
)
def test_public_entrypoints_reject_unsupported_coefficient_types(
    entrypoint_name,
    a,
    b,
):
    entrypoint = getattr(_public_api(), entrypoint_name)

    with pytest.raises(TypeError, match="integer"):
        entrypoint(a, b)


@pytest.mark.parametrize(
    "entrypoint_name",
    ["compute_torsion", "sage_reference", "compare_with_sage"],
)
def test_invalid_coefficients_are_rejected_before_curve_construction(
    entrypoint_name,
    monkeypatch,
):
    core_module = importlib.import_module("rational_torsion.core")
    reference_module = importlib.import_module("rational_torsion.reference")

    def unexpected_curve_construction(*args, **kwargs):
        pytest.fail("curve construction reached for an invalid coefficient")

    monkeypatch.setattr(core_module, "EllipticCurve", unexpected_curve_construction)
    monkeypatch.setattr(
        reference_module,
        "EllipticCurve",
        unexpected_curve_construction,
    )

    with pytest.raises(TypeError, match="integer"):
        getattr(_public_api(), entrypoint_name)(True, 1)
