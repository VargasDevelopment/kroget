from __future__ import annotations

from typing import Tuple

from kroget.core.proposal import ProposalItem


def _item_key(item: ProposalItem) -> tuple[str, str, str]:
    modality = item.modality
    if item.upc:
        return ("upc", item.upc, modality)
    name = item.name.strip().lower()
    return ("name", name, modality)


def merge_proposal_items(
    existing: list[ProposalItem],
    incoming: list[ProposalItem],
    source: str | None = None,
) -> Tuple[list[ProposalItem], int, int]:
    merged_items: list[ProposalItem] = []
    index: dict[tuple[str, str, str], ProposalItem] = {}

    for item in existing:
        if source and source not in item.sources:
            item.sources.append(source)
        index[_item_key(item)] = item
        merged_items.append(item)

    added = 0
    merged = 0

    for item in incoming:
        key = _item_key(item)
        if key in index:
            target = index[key]
            target.quantity += item.quantity
            for src in item.sources:
                if src not in target.sources:
                    target.sources.append(src)
            if source and source not in target.sources:
                target.sources.append(source)
            merged += 1
            continue
        if source and source not in item.sources:
            item.sources.append(source)
        merged_items.append(item)
        index[key] = item
        added += 1

    return merged_items, added, merged
