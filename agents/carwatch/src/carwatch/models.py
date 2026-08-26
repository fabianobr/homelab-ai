"""src/carwatch/models.py"""
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator


class LaunchStage(str, Enum):
    spy = "spy"
    teaser = "teaser"
    world_premiere = "world_premiere"
    specs_release = "specs_release"
    pricing = "pricing"
    on_sale = "on_sale"
    market_launch = "market_launch"
    concept = "concept"


class BrandEntry(BaseModel):
    name: str
    aliases: list[str] = []
    press_domain: str | None = None


class BrandsConfig(BaseModel):
    brands: list[BrandEntry]


class KeywordsConfig(BaseModel):
    positive: dict[str, list[str]]
    negative_strong: list[str]


class ClassifyItem(BaseModel):
    i: int
    is_launch: bool
    stage: LaunchStage | None = None
    brand: str | None = None
    model: str | None = None
    confidence: float


def load_brands_config(path: Path) -> BrandsConfig:
    return BrandsConfig.model_validate(yaml.safe_load(path.read_text()))


def load_keywords_config(path: Path) -> KeywordsConfig:
    return KeywordsConfig.model_validate(yaml.safe_load(path.read_text()))


# The prompt tells the model to use these 5 literal codes directly, but
# LLMs sometimes answer in the article's own natural-language word instead
# (e.g. "petrol") despite the instruction. These are unambiguous synonyms,
# not a business-logic guess -- unlike an invalid `stage`, there's no
# judgment call in mapping "diesel" to "ice".
_POWERTRAIN_TYPE_ALIASES = {
    "petrol": "ice", "gasoline": "ice", "gas": "ice", "diesel": "ice",
    "electric": "bev", "battery": "bev", "battery electric": "bev", "ev": "bev",
    "hybrid": "hev",
    "plug-in hybrid": "phev", "plugin hybrid": "phev", "plug in hybrid": "phev",
    "hydrogen": "fcev", "fuel cell": "fcev",
}


class Powertrain(BaseModel):
    type: Literal["bev", "phev", "hev", "ice", "fcev"]
    power_hp: int | None = None
    torque_nm: int | None = None
    battery_kwh: float | None = None
    range_km: int | None = None
    range_cycle: Literal["WLTP", "CLTC", "EPA"] | None = None
    drivetrain: Literal["fwd", "rwd", "awd"] | None = None
    zero_to_100_s: float | None = None

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type_synonyms(cls, v):
        if isinstance(v, str):
            return _POWERTRAIN_TYPE_ALIASES.get(v.strip().lower(), v)
        return v

    # Observed against the real API: drivetrain="AWD" (uppercase) against a
    # lowercase-only literal. Case-folding to the schema's own casing is a
    # mechanical normalization, not a guess at what the model meant.
    @field_validator("drivetrain", mode="before")
    @classmethod
    def _lowercase_drivetrain(cls, v):
        return v.lower() if isinstance(v, str) else v

    @field_validator("range_cycle", mode="before")
    @classmethod
    def _uppercase_range_cycle(cls, v):
        return v.upper() if isinstance(v, str) else v


class Price(BaseModel):
    amount: float | None = None
    currency: str | None = None
    status: Literal["official", "estimated", "starting_from"] | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _lowercase_status(cls, v):
        return v.lower() if isinstance(v, str) else v


class ExtractedEvent(BaseModel):
    brand: str
    model: str
    generation: str | None = None
    body_type: str | None = None
    stage: LaunchStage
    is_new_generation: bool = False
    markets: list[str] = []
    global_debut: bool = False
    event_date: date | None = None
    sales_start: str | None = None
    powertrain: Powertrain | None = None
    price: Price | None = None
    highlights: list[str] = []
    confidence: float

    # A field's `= default` only applies when the key is absent from the
    # input -- it does NOT cover the model explicitly answering `null` for
    # a field the prompt marks as "never null". Observed against the real
    # API: despite the prompt saying so, is_new_generation/global_debut came
    # back null often enough to fail 100% of a live extract batch. False/[]
    # is exactly what the field's own default already says "unstated" means.
    @field_validator("is_new_generation", "global_debut", mode="before")
    @classmethod
    def _null_means_false(cls, v):
        return False if v is None else v

    @field_validator("markets", "highlights", mode="before")
    @classmethod
    def _null_means_empty_list(cls, v):
        return [] if v is None else v

    # Observed against the real API: the model answered generation=4 (an
    # int ordinal) instead of a generation code/name string. Stringifying
    # an int the model already committed to is a safe, unambiguous
    # normalization -- it's still exactly the value the model meant.
    @field_validator("generation", mode="before")
    @classmethod
    def _stringify_generation(cls, v):
        return str(v) if isinstance(v, int) else v

    # Observed against the real API: despite the prompt already saying
    # "record the entry-level/most relevant version" for multiple engines,
    # the model sometimes wraps that single answer in a list instead of a
    # bare object. Taking the first element is a mechanical implementation
    # of the prompt's own already-stated intent, not a new judgment call.
    @field_validator("powertrain", mode="before")
    @classmethod
    def _first_of_list(cls, v):
        if isinstance(v, list):
            return v[0] if v else None
        return v
