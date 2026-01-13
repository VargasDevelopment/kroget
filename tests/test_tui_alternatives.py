from kroget.core.proposal import ProposalAlternative, ProposalItem
from kroget.tui import _apply_alternatives_to_item


def test_apply_alternatives_sets_missing_upc():
    item = ProposalItem(name="milk", quantity=1, modality="PICKUP")
    alternatives = [ProposalAlternative(upc="000111", description="Milk")]

    updated = _apply_alternatives_to_item(item, alternatives)

    assert updated is True
    assert item.upc == "000111"
    assert item.source == "search"
    assert item.alternatives == alternatives


def test_apply_alternatives_keeps_existing_upc():
    item = ProposalItem(name="eggs", quantity=1, modality="PICKUP", upc="000222")
    alternatives = [ProposalAlternative(upc="000333", description="Eggs")]

    updated = _apply_alternatives_to_item(item, alternatives)

    assert updated is False
    assert item.upc == "000222"
    assert item.source is None
    assert item.alternatives == alternatives
