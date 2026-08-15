from __future__ import annotations

from itertools import product

from sage.all import Integer, QQ, ZZ

from .group import _point_sort_key, exact_order


def _square_divisor_roots(discriminant_abs: Integer) -> list[Integer]:
    if discriminant_abs == 0:
        return [Integer(0)]

    factorization = Integer(discriminant_abs).factor()
    choices = [range(exponent // 2 + 1) for _, exponent in factorization]
    roots = {Integer(0)}

    for exponents in product(*choices):
        value = Integer(1)
        for (prime, _), chosen_exponent in zip(factorization, exponents):
            if chosen_exponent:
                value *= Integer(prime) ** chosen_exponent
        roots.add(value)
        roots.add(-value)

    return sorted(roots)


def two_torsion_points(curve, a: int, b: int) -> list:
    ring = QQ["x"]
    x = ring.gen()
    cubic = x**3 + a * x + b
    identity = curve(0)

    points = []
    for root, _ in cubic.roots():
        point = curve(root, 0)
        if point != identity and 2 * point == identity:
            points.append(point)
    return sorted(set(points), key=_point_sort_key)


def three_torsion_points(curve, a: int, b: int) -> list:
    ring = QQ["x"]
    x = ring.gen()
    division_polynomial = 3 * x**4 + 6 * a * x**2 + 12 * b * x - a**2

    points = set()
    for x_coordinate, _ in division_polynomial.roots():
        rhs = QQ(x_coordinate**3 + a * x_coordinate + b)
        if not rhs.is_square():
            continue

        y_coordinate = rhs.sqrt()
        for sign in (1, -1):
            point = curve(x_coordinate, sign * y_coordinate)
            if exact_order(point) == 3:
                points.add(point)

    return sorted(points, key=_point_sort_key)


def lutz_nagell_candidates(
    curve,
    a: int,
    b: int,
    discriminant: int,
) -> list:
    y_values = _square_divisor_roots(Integer(abs(discriminant)))
    ring = ZZ["x"]
    x = ring.gen()
    points = set()

    for y_coordinate in y_values:
        polynomial = x**3 + Integer(a) * x + Integer(
            b - y_coordinate * y_coordinate
        )
        for x_coordinate, _ in polynomial.roots():
            try:
                point = curve(x_coordinate, y_coordinate)
            except Exception:
                continue
            points.add(point)

    return sorted(points, key=_point_sort_key)
