from kroget.core.proposal import ProposalItem
from kroget.core.proposal_merge import merge_proposal_items


def test_merge_by_upc_modality():
    existing = [ProposalItem(name="Milk", quantity=1, modality="PICKUP", upc="000111")]
    incoming = [ProposalItem(name="Milk", quantity=2, modality="PICKUP", upc="000111")]

    merged_items, added, merged = merge_proposal_items(existing, incoming, source="ListA")

    assert len(merged_items) == 1
    assert merged_items[0].quantity == 3
    assert added == 0
    assert merged == 1


def test_merge_by_name_when_missing_upc():
    existing = [ProposalItem(name="Bread", quantity=1, modality="DELIVERY")]
    incoming = [ProposalItem(name="Bread", quantity=2, modality="DELIVERY")]

    merged_items, added, merged = merge_proposal_items(existing, incoming, source="ListB")

    assert len(merged_items) == 1
    assert merged_items[0].quantity == 3
    assert merged_items[0].sources == ["ListB"]
    assert added == 0
    assert merged == 1


def test_add_new_item():
    existing = [ProposalItem(name="Eggs", quantity=1, modality="PICKUP", upc="000222")]
    incoming = [ProposalItem(name="Milk", quantity=1, modality="PICKUP", upc="000111")]

    merged_items, added, merged = merge_proposal_items(existing, incoming, source="ListC")

    assert len(merged_items) == 2
    assert added == 1
    assert merged == 0
