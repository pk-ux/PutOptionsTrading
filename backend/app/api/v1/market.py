"""
Market clock endpoint — US equities session time from Alpaca.
"""

from fastapi import APIRouter

from ...core.market_clock import clock_to_dict, get_market_clock

router = APIRouter()


@router.get("/market-clock")
async def get_market_clock_endpoint():
    """Current NYSE session clock (America/New_York), sourced from Alpaca."""
    return clock_to_dict(get_market_clock())
