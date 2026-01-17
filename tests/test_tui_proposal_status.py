from kroget.core.proposal import Proposal, ProposalItem
from kroget.tui import _proposal_status_text


def test_proposal_status_text_counts_items() -> None:
    proposal = Proposal(
        version="1",
        created_at="2024-01-01T00:00:00Z",
        location_id="123",
        items=[
            ProposalItem(name="Milk", quantity=2, modality="PICKUP", upc="000111"),
            ProposalItem(name="Eggs", quantity=1, modality="DELIVERY", upc=None),
        ],
        sources=["UnitTest"],
    )

    assert _proposal_status_text(proposal) == "Proposal: 2 items | Sources: UnitTest"
