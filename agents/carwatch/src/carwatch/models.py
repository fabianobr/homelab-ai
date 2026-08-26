"""src/carwatch/models.py"""
from enum import Enum
from pathlib import Path

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
