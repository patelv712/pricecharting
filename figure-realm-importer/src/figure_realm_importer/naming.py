from __future__ import annotations

import re
from collections import defaultdict

from .models import FigureRecord, SeriesRecord


NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
SPACE_RE = re.compile(r"\s+")
PARENTHETICAL_SUFFIX_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
SUBSERIES_ALIASES = {
    "poptowns": "Pop! Town",
}


def normalized_key(value: str) -> str:
    return NON_ALNUM_RE.sub("", value.casefold())


def canonical_subseries(value: str) -> str:
    cleaned = SPACE_RE.sub(" ", value).strip()
    return SUBSERIES_ALIASES.get(normalized_key(cleaned), cleaned)


def without_repeated_model_number(value: str, model_number: str) -> str:
    if not model_number:
        return value
    suffix = re.compile(rf"\s+#\s*{re.escape(model_number)}\s*$", re.I)
    return suffix.sub("", value).strip()


def proposed_set_name(series: SeriesRecord, subseries: str = "") -> str:
    source_key = normalized_key(series.source_name)
    universe_key = normalized_key(series.universe_name)
    if source_key == universe_key or source_key.startswith(universe_key):
        base = series.source_name
    else:
        base = f"{series.universe_name} - {series.source_name}"
    set_subseries = canonical_subseries(subseries)
    subseries_key = normalized_key(set_subseries)
    if set_subseries and not source_key.endswith(subseries_key):
        base = f"{base} - {set_subseries}"
    return f"{base} ({series.manufacturer})" if series.manufacturer else base


def plain_name_and_descriptors(value: str) -> tuple[str, tuple[str, ...]]:
    """Separate trailing parenthetical descriptors from a possible plain product name."""
    base = value.strip()
    descriptors: list[str] = []
    while match := PARENTHETICAL_SUFFIX_RE.search(base):
        descriptor = SPACE_RE.sub(" ", match.group(1)).strip()
        if descriptor:
            descriptors.insert(0, descriptor)
        base = base[: match.start()].strip()
    return base or value.strip(), tuple(descriptors)


def _secondary_descriptors(
    descriptor_lists: list[tuple[str, ...]],
) -> list[str] | None:
    """Choose a short distinguishing descriptor after removing words shared by the subgroup."""
    if not descriptor_lists:
        return []
    normalized_lists = [
        {normalized_key(descriptor): descriptor for descriptor in descriptors}
        for descriptors in descriptor_lists
    ]
    common = set(normalized_lists[0])
    for values in normalized_lists[1:]:
        common &= set(values)

    choices: list[str] = []
    for descriptors in descriptor_lists:
        remaining = [
            descriptor for descriptor in descriptors if normalized_key(descriptor) not in common
        ]
        choices.append(remaining[-1] if remaining else "")
    normalized_choices = [normalized_key(choice) for choice in choices]
    if len(set(normalized_choices)) != len(normalized_choices):
        return None
    return choices


def _apply_funko_variants(group: list[FigureRecord], plain_name: str) -> bool:
    """Use Figure Realm Exclusive (the store/exclusive stamp) before other Funko descriptors."""
    by_exclusive: dict[str, list[FigureRecord]] = defaultdict(list)
    descriptors_by_id: dict[str, tuple[str, ...]] = {}
    for item in group:
        _, descriptors = plain_name_and_descriptors(item.proposed_product_name)
        descriptors_by_id[item.figure_id] = descriptors
        by_exclusive[normalized_key(item.exclusive)].append(item)

    variants: dict[str, str] = {}
    for exclusive_key, subgroup in by_exclusive.items():
        exclusive = subgroup[0].exclusive.strip()
        if len(subgroup) == 1:
            variants[subgroup[0].figure_id] = exclusive
            continue

        secondary = _secondary_descriptors(
            [descriptors_by_id[item.figure_id] for item in subgroup]
        )
        if secondary is None:
            return False
        for item, descriptor in zip(subgroup, secondary, strict=True):
            parts = [value for value in (exclusive, descriptor) if value]
            variants[item.figure_id] = " ".join(parts)

    normalized_variants = [normalized_key(variants[item.figure_id]) for item in group]
    if len(set(normalized_variants)) != len(normalized_variants):
        return False

    for item in group:
        variant = variants[item.figure_id]
        item.proposed_product_name = f"{plain_name} [{variant}]" if variant else plain_name
        item.naming_reason = (
            "Funko exclusive/store distinguishes a duplicate plain name and model number"
            if item.exclusive
            else "base Funko version needs no variant"
        )
    return True


def _apply_visible_descriptor_variants(group: list[FigureRecord], plain_name: str) -> bool:
    descriptors = [
        plain_name_and_descriptors(item.proposed_product_name)[1] for item in group
    ]
    variants = _secondary_descriptors(descriptors)
    if variants is None:
        return False
    for item, variant in zip(group, variants, strict=True):
        item.proposed_product_name = f"{plain_name} [{variant}]" if variant else plain_name
        item.naming_reason = (
            "visible parenthetical descriptor distinguishes a duplicate plain name and model number"
            if variant
            else "base version needs no variant"
        )
    return True


def apply_naming(figures: list[FigureRecord], series_by_id: dict[str, SeriesRecord]) -> None:
    for figure in figures:
        series_key = figure.series_identity or figure.series_id
        figure.proposed_set_name = proposed_set_name(
            series_by_id[series_key], figure.subseries
        )
        source_name = SPACE_RE.sub(" ", figure.source_name).strip()
        figure.proposed_product_name = without_repeated_model_number(
            source_name, figure.model_number
        )
        figure.naming_reason = "source name is unique within proposed set and model number"

    collisions: dict[tuple[str, str, str], list[FigureRecord]] = defaultdict(list)
    for figure in figures:
        collision_name, _ = plain_name_and_descriptors(figure.proposed_product_name)
        collisions[
            (
                normalized_key(figure.proposed_set_name),
                normalized_key(collision_name),
                normalized_key(figure.model_number),
            )
        ].append(figure)

    for group in collisions.values():
        if len(group) < 2:
            continue

        if all(normalized_key(item.manufacturer) == "funko" for item in group):
            plain_name, _ = plain_name_and_descriptors(group[0].proposed_product_name)
            if _apply_funko_variants(group, plain_name):
                continue
            for item in group:
                item.review_required = True
                item.naming_reason = (
                    "Funko duplicate needs a unique exclusive/store or visible descriptor"
                )
            continue

        plain_name, _ = plain_name_and_descriptors(group[0].proposed_product_name)
        if _apply_visible_descriptor_variants(group, plain_name):
            continue

        years = [item.release_year for item in group]
        if all(years) and len(set(years)) == len(group):
            for item in group:
                item.proposed_product_name = f"{item.proposed_product_name} [{item.release_year}]"
                item.naming_reason = "release year distinguishes a duplicate name and model number"
            continue

        for item in group:
            item.review_required = True
            item.naming_reason = "duplicate name and model number needs a marketplace-visible variant"
