"""src/carwatch/models.py"""
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel


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


class Powertrain(BaseModel):
    type: Literal["bev", "phev", "hev", "ice", "fcev"]
    power_hp: int | None = None
    torque_nm: int | None = None
    battery_kwh: float | None = None
    range_km: int | None = None
    range_cycle: Literal["WLTP", "CLTC", "EPA"] | None = None
    drivetrain: Literal["fwd", "rwd", "awd"] | None = None
    zero_to_100_s: float | None = None


class Price(BaseModel):
    amount: float | None = None
    currency: str | None = None
    status: Literal["official", "estimated", "starting_from"] | None = None


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
