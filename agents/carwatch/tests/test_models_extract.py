"""tests/test_models_extract.py"""
import pytest
from pydantic import ValidationError

from carwatch.models import ExtractedEvent, Powertrain, Price


def test_powertrain_requires_only_type():
    pt = Powertrain(type="bev")
    assert pt.power_hp is None
    assert pt.range_cycle is None


def test_powertrain_normalizes_natural_language_fuel_words():
    """A real extract call against the live API returned "petrol"/"diesel"
    despite the prompt instructing the model to answer with the literal
    schema codes -- these are unambiguous synonyms the model reaches for
    naturally, not a business-logic guess, so normalizing them is safe.
    model_validate (not the keyword constructor) matches how this data
    actually arrives in production: a dict parsed from the LLM's JSON.
    """
    assert Powertrain.model_validate({"type": "petrol"}).type == "ice"
    assert Powertrain.model_validate({"type": "Diesel"}).type == "ice"
    assert Powertrain.model_validate({"type": "Electric"}).type == "bev"
    assert Powertrain.model_validate({"type": "hybrid"}).type == "hev"
    assert Powertrain.model_validate({"type": "plug-in hybrid"}).type == "phev"


def test_powertrain_rejects_truly_invalid_type():
    with pytest.raises(ValidationError):
        Powertrain.model_validate({"type": "nonsense_fuel_type"})


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


def test_extracted_event_treats_explicit_null_as_the_field_default():
    """A real extract call against the live API returned is_new_generation
    and global_debut as explicit `null` despite the prompt instructing
    "never null" for them -- Pydantic's `= False` default only covers a
    MISSING key, not one present with value null, so this raised
    ValidationError on every single real-world call before this fix.
    model_validate (not the keyword constructor) matches how this data
    actually arrives in production: a dict parsed from the LLM's JSON,
    which is what carries an explicit `null` rather than a missing key.
    """
    event = ExtractedEvent.model_validate({
        "brand": "Mazda",
        "model": "MX-5",
        "stage": "specs_release",
        "is_new_generation": None,
        "global_debut": None,
        "markets": None,
        "highlights": None,
        "confidence": 0.7,
    })
    assert event.is_new_generation is False
    assert event.global_debut is False
    assert event.markets == []
    assert event.highlights == []


def test_extracted_event_stringifies_an_integer_generation():
    """A real extract call against the live API returned generation=4 (an
    ordinal int) instead of a generation code/name string.
    """
    event = ExtractedEvent.model_validate({
        "brand": "Mazda",
        "model": "MX-5",
        "generation": 4,
        "stage": "specs_release",
        "confidence": 0.7,
    })
    assert event.generation == "4"


def test_extracted_event_takes_the_first_powertrain_of_a_list():
    """A real extract call against the live API wrapped its single-engine
    answer in a list instead of a bare object, despite the prompt already
    saying to record only the entry-level/most relevant version.
    """
    event = ExtractedEvent.model_validate({
        "brand": "Mazda",
        "model": "MX-5",
        "stage": "specs_release",
        "powertrain": [{"type": "ice", "power_hp": 130}, {"type": "ice", "power_hp": 181}],
        "confidence": 0.7,
    })
    assert event.powertrain.type == "ice"
    assert event.powertrain.power_hp == 130


def test_extracted_event_treats_an_empty_powertrain_list_as_none():
    event = ExtractedEvent.model_validate({
        "brand": "Mazda",
        "model": "MX-5",
        "stage": "specs_release",
        "powertrain": [],
        "confidence": 0.7,
    })
    assert event.powertrain is None
