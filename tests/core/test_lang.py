"""Language packs: rules no vocabulary may break."""
from neetscape import infer


def test_german_text_is_not_read_with_polish_words():
    # "kontrakt"/"B2B" mean b2b for Polish boards only
    assert infer.contracts_from_text("B2B-Vertrieb", ("de", "en")) == []
    assert infer.contracts_from_text("B2B", ("pl", "en")) == ["b2b"]
    assert infer.mode_from_text("Homeoffice möglich", ("de", "en")) == "hybrid"
    assert infer.mode_from_text("Home office", ("pl", "en")) == "remote"
