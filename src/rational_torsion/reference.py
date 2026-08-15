from __future__ import annotations

from sage.all import EllipticCurve, QQ

from .core import compute_torsion
from .group import _point_sort_key
from .model import (
    ComparisonResult,
    ReferenceResult,
    _require_integer_coefficients,
    discriminant,
)


def sage_reference(a: int, b: int) -> ReferenceResult:
    _require_integer_coefficients(a, b)
    if discriminant(a, b) == 0:
        raise ValueError("Singular curve: discriminant is zero")

    curve = EllipticCurve(QQ, [a, b])
    subgroup = curve.torsion_subgroup()
    invariants = tuple(int(value) for value in subgroup.invariants())

    if not invariants:
        torsion_type = "Z/1"
    elif len(invariants) == 1:
        torsion_type = f"Z/{invariants[0]}"
    else:
        torsion_type = " x ".join(f"Z/{value}" for value in invariants)

    order = 1
    for invariant in invariants:
        order *= invariant

    generators = [
        generator.element() if hasattr(generator, "element") else generator
        for generator in subgroup.gens()
    ]

    return ReferenceResult(
        torsion_type=torsion_type,
        order=order,
        generators=sorted(generators, key=_point_sort_key),
    )


def compare_with_sage(a: int, b: int) -> ComparisonResult:
    _require_integer_coefficients(a, b)
    ours = compute_torsion(a, b)
    reference = sage_reference(a, b)
    match = (
        ours.torsion_type == reference.torsion_type
        and len(ours.torsion_points) == reference.order
    )
    return ComparisonResult(ours=ours, reference=reference, match=match)
