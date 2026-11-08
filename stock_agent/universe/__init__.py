"""Universe providers."""

from stock_agent.universe.custom import CustomListUniverse
from stock_agent.universe.nasdaq import NasdaqUniverse
from stock_agent.universe.sp500 import SP500Universe

__all__ = ["CustomListUniverse", "NasdaqUniverse", "SP500Universe", "load_universe"]


def load_universe(spec: str, *, cache_dir):
    if spec == "sp500":
        return SP500Universe(cache_dir=cache_dir)
    if spec == "nasdaq":
        return NasdaqUniverse(cache_dir=cache_dir)
    if spec.startswith("custom:"):
        return CustomListUniverse(spec.split(":", 1)[1])
    raise ValueError(f"Unknown universe: {spec}")
