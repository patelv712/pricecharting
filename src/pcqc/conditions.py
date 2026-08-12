"""Authoritative PriceCharting TCG condition and review-status mappings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionDefinition:
    condition_id: int
    name: str
    price_key: str | None


# Condition IDs and price-key meanings follow the PriceCharting API docs.
CONDITIONS: dict[int, ConditionDefinition] = {
    1: ConditionDefinition(1, "Ungraded", "loose-price"),
    2: ConditionDefinition(2, "Grade 8", "new-price"),
    3: ConditionDefinition(3, "Grade 7", "cib-price"),
    5: ConditionDefinition(5, "Grade 9", "graded-price"),
    6: ConditionDefinition(6, "Grade 9.5", "box-only-price"),
    7: ConditionDefinition(7, "PSA 10", "manual-only-price"),
    8: ConditionDefinition(8, "BGS 10", "bgs-10-price"),
    9: ConditionDefinition(9, "Grade 1", "condition-9-price"),
    10: ConditionDefinition(10, "Grade 2", "condition-10-price"),
    13: ConditionDefinition(13, "Grade 3", "condition-13-price"),
    14: ConditionDefinition(14, "Grade 4", "condition-14-price"),
    15: ConditionDefinition(15, "Grade 5", "condition-15-price"),
    16: ConditionDefinition(16, "Grade 6", "condition-16-price"),
    17: ConditionDefinition(17, "CGC 10", "condition-17-price"),
    18: ConditionDefinition(18, "SGC 10", "condition-18-price"),
    19: ConditionDefinition(19, "CGC 10 Pristine", "condition-19-price"),
    20: ConditionDefinition(20, "BGS 10 Black", "condition-20-price"),
    21: ConditionDefinition(21, "TAG 10", "condition-21-price"),
    22: ConditionDefinition(22, "ACE 10", "condition-22-price"),
}


# These are the internal status slugs observed in the reviewed-sale export.
STATUS_SLUG_TO_CONDITION_ID: dict[str, int] = {
    "used": 1,
    "new": 2,
    "cib": 3,
    "gradednew": 5,
    "boxonly": 6,
    "manualonly": 7,
    "looseandbox": 8,
    "looseandmanual": 9,
    "boxandmanual": 10,
    "gradedcib": 13,
    "gradefour": 14,
    "gradefive": 15,
    "gradesix": 16,
    "gradeseventeen": 17,
    "gradeeighteen": 18,
}


def condition_name(condition_id: int) -> str:
    try:
        return CONDITIONS[condition_id].name
    except KeyError as exc:
        raise ValueError(f"Unsupported condition id: {condition_id}") from exc


def price_key_for_condition(condition_id: int) -> str | None:
    definition = CONDITIONS.get(condition_id)
    return definition.price_key if definition else None

