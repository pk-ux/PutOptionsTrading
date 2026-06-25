"""
Breakout Scanner - app integration glue.

This is the ONLY app-aware part of the module. It loads settings/universe from
the database, runs the portable scanner, persists results, and publishes the
top picks into the "Momentum Stocks" system Trade Idea. Keep it separate so the
rest of the module stays portable.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from ...core.config import get_settings
from ...core.database import SessionLocal
from ...models import BreakoutScannerSettings, BreakoutScanResult, TradeIdea
from . import run_scan
from .providers.unusual_whales import UnusualWhalesProvider
from .providers.yahoo_provider import YahooPriceProvider
from .types import ScannerConfig

logger = logging.getLogger(__name__)

MOMENTUM_TRADE_IDEA_NAME = "Momentum Stocks"
MOMENTUM_TRADE_IDEA_DESCRIPTION = (
    "Auto-generated pre-breakout momentum picks from the Breakout Scanner"
)

# A scan that has been "running" longer than this is assumed dead (e.g. the
# server restarted mid-scan) and is auto-reset so it can't permanently block runs.
STALE_RUNNING_MINUTES = 15


def get_or_create_settings(db) -> BreakoutScannerSettings:
    """Fetch the singleton settings row, creating it with defaults if missing."""
    settings = db.query(BreakoutScannerSettings).filter(
        BreakoutScannerSettings.id == 1
    ).first()
    if not settings:
        settings = BreakoutScannerSettings(id=1)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def reset_if_stale(db, settings: BreakoutScannerSettings) -> bool:
    """If a scan has been 'running' too long it was almost certainly killed (a
    background task dies when the server restarts). Mark it failed so new runs
    aren't blocked. Returns True if a reset happened.
    """
    if settings.last_run_status != "running":
        return False
    ref = settings.updated_at  # bumped when the run was marked 'running'
    if ref is None or (datetime.utcnow() - ref) > timedelta(minutes=STALE_RUNNING_MINUTES):
        settings.last_run_status = "error"
        settings.last_run_message = (
            "Previous scan was interrupted (likely a server restart). You can run again."
        )
        db.commit()
        return True
    return False


def reset_status(db, message: str = "Status reset") -> BreakoutScannerSettings:
    """Force the scan status back to idle (manual admin override)."""
    settings = get_or_create_settings(db)
    settings.last_run_status = "idle"
    settings.last_run_message = message
    db.commit()
    db.refresh(settings)
    return settings


def _build_config(settings: BreakoutScannerSettings) -> ScannerConfig:
    config = ScannerConfig(
        top_n=settings.top_n,
        deep_dive_n=settings.deep_dive_n,
        use_unusual_whales=settings.use_unusual_whales,
        min_price=settings.min_price,
        max_price=settings.max_price,
        min_avg_volume=settings.min_avg_volume,
        require_above_sma200=settings.require_above_sma200,
        typical_csp_dte=settings.typical_csp_dte,
    )
    weights = settings.get_weights()
    if weights:
        config.weights = {**config.weights, **weights}
    return config


def _set_status(db, settings: BreakoutScannerSettings, status: str, message: Optional[str] = None) -> None:
    settings.last_run_status = status
    settings.last_run_message = message
    if status in ("success", "error"):
        settings.last_run_at = datetime.utcnow()
    db.commit()


def _publish_trade_idea(db, symbols: list) -> None:
    """Create or update the 'Momentum Stocks' system trade idea with `symbols`."""
    if not symbols:
        return
    idea = db.query(TradeIdea).filter(
        TradeIdea.is_system == True,  # noqa: E712
        TradeIdea.name == MOMENTUM_TRADE_IDEA_NAME,
    ).first()

    if idea:
        idea.set_symbols_list(symbols)
        idea.description = MOMENTUM_TRADE_IDEA_DESCRIPTION
    else:
        max_order = db.query(TradeIdea).filter(TradeIdea.is_system == True).count()  # noqa: E712
        idea = TradeIdea(
            name=MOMENTUM_TRADE_IDEA_NAME,
            description=MOMENTUM_TRADE_IDEA_DESCRIPTION,
            is_system=True,
            is_default=False,
            user_id=None,
            display_order=max_order,
            symbols=",".join(symbols),
        )
        db.add(idea)
    db.commit()


def _persist_results(db, result) -> None:
    """Replace previous scan results with the latest run's candidates."""
    db.query(BreakoutScanResult).delete()
    for c in result.candidates:
        db.add(
            BreakoutScanResult(
                run_at=result.run_at,
                symbol=c.symbol,
                score=c.score,
                rank=c.rank,
                setup_type=c.setup_type,
                pivot_price=c.pivot_price,
                current_price=c.current_price,
                iv_rank=c.iv_rank,
                implied_move=c.implied_move,
                net_call_premium=c.net_call_premium,
                bullish_flow_score=c.bullish_flow_score,
                gex_regime=c.gex_regime,
                dark_pool_accum=c.dark_pool_accum,
                smart_money=c.smart_money,
                next_earnings_date=c.next_earnings_date,
                earnings_flag=c.earnings_flag,
                suggested_put_strike=c.suggested_put_strike,
                factor_breakdown=json.dumps(c.factor_breakdown or {}),
            )
        )
    db.commit()


def run_and_publish() -> Dict[str, Any]:
    """Run a full scan using DB settings and publish results.

    Creates its own DB session so it is safe to call from a background task or
    a CLI entrypoint. Returns a summary dict.
    """
    db = SessionLocal()
    settings_row = None
    try:
        settings_row = get_or_create_settings(db)
        universe = settings_row.get_universe_list()
        if not universe:
            _set_status(db, settings_row, "error", "Scan universe is empty. Add tickers first.")
            return {"status": "error", "message": "Scan universe is empty"}

        _set_status(db, settings_row, "running", "Scan in progress...")

        config = _build_config(settings_row)

        # Providers
        price_provider = YahooPriceProvider()
        uw_provider = None
        if config.use_unusual_whales:
            uw_key = get_settings().UNUSUAL_WHALES_API_KEY
            if uw_key:
                # ~5 req/s spacing smooths bursts and reduces 429s during the
                # per-ticker deep-dive pass.
                uw_provider = UnusualWhalesProvider(api_key=uw_key, min_interval=0.2)
            else:
                logger.warning("use_unusual_whales is on but UNUSUAL_WHALES_API_KEY is not set")

        result = run_scan(
            tickers=universe,
            config=config,
            price_provider=price_provider,
            uw_provider=uw_provider,
            logger=logger,
        )

        if uw_provider is not None:
            uw_provider.close()

        _persist_results(db, result)
        _publish_trade_idea(db, result.top_symbols)

        msg = (
            f"Scanned {result.scanned}/{result.universe_size} tickers, "
            f"published {len(result.candidates)} picks"
            + (" (UW active)" if result.used_unusual_whales else " (no UW)")
        )
        if result.warnings:
            msg += " | " + "; ".join(result.warnings)
        _set_status(db, settings_row, "success", msg)

        return {
            "status": "success",
            "message": msg,
            "result": result.to_dict(),
        }
    except Exception as e:  # pragma: no cover
        logger.exception("Breakout scan failed")
        if settings_row is not None:
            try:
                _set_status(db, settings_row, "error", f"Scan failed: {e}")
            except Exception:
                db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()
