"""tests/test_embeddings.py"""
import pytest

from carwatch.embeddings import embed_text

pytestmark = pytest.mark.embeddings  # register in pyproject.toml's pytest markers if not already


def test_embed_text_returns_384_dimensions():
    vector = embed_text("BYD Seal 06 world premiere")
    assert len(vector) == 384
    assert all(isinstance(v, float) for v in vector)


def test_embed_text_is_deterministic_for_same_input():
    a = embed_text("BYD Seal 06 world premiere")
    b = embed_text("BYD Seal 06 world premiere")
    assert a == b


def test_embed_text_multilingual_inputs_are_close_in_semantic_space():
    import math

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        return dot / (norm_a * norm_b)

    en = embed_text("BYD Seal 06 world premiere")
    zh = embed_text("比亚迪海豹06首发")
    unrelated = embed_text("quarterly earnings report layoffs")

    assert cosine(en, zh) > cosine(en, unrelated)
