from __future__ import annotations

from sage.all import EllipticCurve, QQ

from .candidates import (
    lutz_nagell_candidates,
    three_torsion_points,
    two_torsion_points,
)
from .group import (
    _point_sort_key,
    _point_to_str,
    exact_order,
    select_generators,
    subgroup_generated_by,
    type_from_points,
)
from .model import (
    ALLOWED_TYPES,
    HIGHER_BRANCH_ORDERS,
    TorsionResult,
    _require_integer_coefficients,
    discriminant,
)


def compute_torsion(a: int, b: int) -> TorsionResult:
    _require_integer_coefficients(a, b)
    curve_discriminant = discriminant(a, b)
    if curve_discriminant == 0:
        raise ValueError("Singular curve: discriminant is zero")

    curve = EllipticCurve(QQ, [a, b])
    identity = curve(0)
    decision_log: list[str] = []
    branch_hits: dict[str, bool] = {}
    verified_points = set()

    points_of_order_two = two_torsion_points(curve, a, b)
    if points_of_order_two:
        decision_log.append(
            "A: found "
            f"{len(points_of_order_two)} nonzero 2-torsion points from cubic roots"
        )
        branch_hits["A_2torsion"] = True
        verified_points.update(points_of_order_two)
    else:
        decision_log.append("A: no rational cubic roots; 2-torsion rejected")
        branch_hits["A_2torsion"] = False

    points_of_order_three = three_torsion_points(curve, a, b)
    if points_of_order_three:
        decision_log.append(
            "B: found "
            f"{len(points_of_order_three)} points of order 3 from the division polynomial"
        )
        branch_hits["B_3torsion"] = True
        verified_points.update(points_of_order_three)
    else:
        decision_log.append("B: rational 3-torsion candidates were not confirmed")
        branch_hits["B_3torsion"] = False

    candidates = lutz_nagell_candidates(curve, a, b, curve_discriminant)
    points_by_order = {order: [] for order in HIGHER_BRANCH_ORDERS}

    for point in candidates:
        if point == identity:
            continue
        order = exact_order(point)
        if order is None:
            continue
        verified_points.add(point)
        if order in points_by_order:
            points_by_order[order].append(point)

    for order in HIGHER_BRANCH_ORDERS:
        branch_key = f"C_order_{order}"
        if points_by_order[order]:
            branch_hits[branch_key] = True
            witness = points_by_order[order][0]
            decision_log.append(
                f"C{order}: confirmed point {_point_to_str(witness)} of order {order}"
            )
        else:
            branch_hits[branch_key] = False
            decision_log.append(
                f"C{order}: no confirmed candidate of order {order}"
            )

    torsion_points = subgroup_generated_by(
        curve,
        [identity] + sorted(verified_points, key=_point_sort_key),
    )
    torsion_type, _ = type_from_points(torsion_points)

    if torsion_type not in ALLOWED_TYPES:
        decision_log.append(f"Computed type {torsion_type} is outside Mazur's list")

    return TorsionResult(
        a=a,
        b=b,
        discriminant=curve_discriminant,
        torsion_type=torsion_type,
        generators=select_generators(torsion_points),
        torsion_points=torsion_points,
        decision_log=decision_log,
        branch_hits=branch_hits,
    )
