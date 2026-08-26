"""tests/test_models_extract.py"""
import pytest
from pydantic import ValidationError

from carwatch.models import ExtractedEvent, Powertrain, Price


def test_powertrain_requires_only_type():
    pt = Powertrain(type="bev")
    assert pt.power_hp is None
    assert pt.range_cycle is None


def test_powertrain_rejects_invalid_type():
    with pytest.raises(ValidationError):
        Powertrain(type="diesel")


def test_price_all_fields_optional():
    price = Price()
    assert price.amount is None


def test_extracted_event_defaults_is_new_generation_to_false():
    event = ExtractedEvent(
        brand="BYD",
        model="Seal 06",
        generation=None,
        body_type="sedan",
        stage="world_premiere",
        markets=["CN"],
        event_date=None,
        sales_start=None,
        powertrain=None,
        price=None,
        highlights=["Estreia mundial do novo sedã elétrico"],
        confidence=0.9,
    )
    assert event.is_new_generation is False


def test_extracted_event_requires_brand_and_model():
    with pytest.raises(ValidationError):
        ExtractedEvent(
            model="Seal 06",
            stage="world_premiere",
            highlights=[],
            confidence=0.9,
        )
