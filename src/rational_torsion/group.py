from __future__ import annotations

from collections.abc import Sequence

from sage.all import QQ


def _qq_to_str(value) -> str:
    value = QQ(value)
    if value.denominator() == 1:
        return str(value.numerator())
    return f"{value.numerator()}/{value.denominator()}"


def _point_sort_key(point) -> tuple[int, str, str]:
    if point.is_zero():
        return (0, "0", "0")
    return (1, _qq_to_str(point[0]), _qq_to_str(point[1]))


def _point_to_str(point) -> str:
    if hasattr(point, "element"):
        point = point.element()
    if point.is_zero():
        return "O"
    return f"({_qq_to_str(point[0])}, {_qq_to_str(point[1])})"


def exact_order(point, max_order: int = 24) -> int | None:
    curve = point.curve()
    identity = curve(0)
    if point == identity:
        return 1
    for order in range(2, max_order + 1):
        if order * point == identity:
            return order
    return None


def subgroup_generated_by(curve, generators: Sequence) -> list:
    identity = curve(0)
    subgroup = {identity}
    nonzero_generators = [point for point in generators if not point.is_zero()]
    if not nonzero_generators:
        return [identity]

    changed = True
    while changed:
        changed = False
        for point in list(subgroup):
            for generator in nonzero_generators:
                for next_point in (point + generator, point - generator):
                    if next_point not in subgroup:
                        subgroup.add(next_point)
                        changed = True
    return sorted(subgroup, key=_point_sort_key)


def type_from_points(points: Sequence) -> tuple[str, tuple[int, ...]]:
    if not points:
        return "Z/1", (1,)

    curve = points[0].curve()
    identity = curve(0)
    group_order = len(points)
    exponent = 1

    for point in points:
        if point == identity:
            continue
        order = exact_order(point)
        if order is not None:
            exponent = max(exponent, order)

    if group_order == 1:
        invariants = ()
        torsion_type = "Z/1"
    elif group_order == exponent:
        invariants = (group_order,)
        torsion_type = f"Z/{group_order}"
    else:
        first_invariant = group_order // exponent
        invariants = (first_invariant, exponent)
        torsion_type = f"Z/{first_invariant} x Z/{exponent}"

    return torsion_type, invariants


def select_generators(points: Sequence) -> list:
    if not points:
        return []

    curve = points[0].curve()
    identity = curve(0)
    nonzero_points = [point for point in points if point != identity]
    if not nonzero_points:
        return []

    orders = {point: exact_order(point) for point in nonzero_points}
    ordered_points = sorted(
        nonzero_points,
        key=lambda point: (
            -(orders[point] or 0),
            _qq_to_str(point[0]),
            _qq_to_str(point[1]),
        ),
    )
    target_size = len(points)

    for point in ordered_points:
        if len(subgroup_generated_by(curve, [point])) == target_size:
            return [point]

    for index, first_point in enumerate(ordered_points):
        for second_point in ordered_points[index + 1 :]:
            if (
                len(subgroup_generated_by(curve, [first_point, second_point]))
                == target_size
            ):
                return [first_point, second_point]

    return ordered_points[:2]
