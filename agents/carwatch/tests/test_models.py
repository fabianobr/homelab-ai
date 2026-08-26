"""tests/test_models.py"""
from pathlib import Path

import pytest
from pydantic import ValidationError

from carwatch.models import (
    ClassifyItem,
    LaunchStage,
    load_brands_config,
    load_keywords_config,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_brands_config_parses_aliases_and_optional_press_domain():
    cfg = load_brands_config(FIXTURES / "brands_sample.yaml")

    assert len(cfg.brands) == 3
    vw = next(b for b in cfg.brands if b.name == "Volkswagen")
    assert vw.aliases == ["VW"]
    byd = next(b for b in cfg.brands if b.name == "BYD")
    assert byd.press_domain is None


def test_load_keywords_config_parses_positive_and_negative():
    cfg = load_keywords_config(FIXTURES / "keywords_sample.yaml")

    assert "unveil" in cfg.positive["en"]
    assert "lançamento" in cfg.positive["pt"]
    assert "recall" in cfg.negative_strong


def test_launch_stage_matches_db_enum_members():
    expected = {
        "spy",
        "teaser",
        "world_premiere",
        "specs_release",
        "pricing",
        "on_sale",
        "market_launch",
        "concept",
    }
    assert {member.value for member in LaunchStage} == expected


def test_classify_item_rejects_unknown_stage():
    with pytest.raises(ValidationError):
        ClassifyItem(i=0, is_launch=True, stage="not-a-real-stage", brand="X", model="Y", confidence=0.9)


def test_classify_item_accepts_valid_stage():
    item = ClassifyItem(
        i=0, is_launch=True, stage="world_premiere", brand="BYD", model="Seal 06", confidence=0.92
    )
    assert item.stage is LaunchStage.world_premiere
