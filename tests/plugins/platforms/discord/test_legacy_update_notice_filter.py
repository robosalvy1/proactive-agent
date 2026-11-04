"""The Discord history filter must keep recognising update notices posted before the Tandem rename."""

import pytest

from plugins.platforms.discord.adapter import _looks_like_nonconversational_history_message


@pytest.mark.parametrize("product", ["Hermes", "Tandem"])
@pytest.mark.parametrize("outcome", ["finished.", "failed.", "timed out."])
def test_update_notices_from_either_spelling_are_not_conversational(product, outcome):
    assert _looks_like_nonconversational_history_message(f"✅ {product} update {outcome}")
    assert _looks_like_nonconversational_history_message(f"❌ {product} update {outcome}")


def test_ordinary_messages_stay_conversational():
    assert not _looks_like_nonconversational_history_message("Tandem update when you have a minute?")
