from __future__ import annotations

from dataclasses import dataclass


ALLOWED_TYPES = {
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
}

HIGHER_BRANCH_ORDERS = (4, 5, 6, 7, 8, 9, 10, 12)


def _require_integer_coefficients(a: int, b: int) -> None:
    if type(a) is not int or type(b) is not int:
        raise TypeError("curve coefficients a and b must be integers")


@dataclass
class TorsionResult:
    a: int
    b: int
    discriminant: int
    torsion_type: str
    generators: list
    torsion_points: list
    decision_log: list[str]
    branch_hits: dict[str, bool]


@dataclass
class ReferenceResult:
    torsion_type: str
    order: int
    generators: list


@dataclass
class ComparisonResult:
    ours: TorsionResult
    reference: ReferenceResult
    match: bool


def discriminant(a: int, b: int) -> int:
    return int(-16 * (4 * a**3 + 27 * b**2))
