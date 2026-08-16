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

from sqlalchemy import inspect as sa_inspect, text

from ...core.config import get_settings
from ...core.database import SessionLocal, engine
from ...models import BreakoutScannerSettings, BreakoutScanResult, TradeIdea
from ...models.breakout_scanner import (
    DEFAULT_AUTO_SCAN_DAYS,
    DEFAULT_AUTO_SCAN_TIME,
    DEFAULT_AUTO_SCAN_TIMEZONE,
)
from . import run_scan
from .providers.alpaca_provider import AlpacaPriceProvider
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


# New columns added by the scanner upgrade. The app uses create_all (no Alembic),
# so on an already-provisioned DB we add any missing columns defensively here.
# (name -> SQL type valid for both SQLite and Postgres)
_RESULT_COLUMNS = {
    "volume_expansion": "FLOAT",
    "pct_from_52wk_high": "FLOAT",
    "pct_to_pivot": "FLOAT",
    "iv_vs_realized": "FLOAT",
    "gamma_wall": "FLOAT",
    "max_pain": "FLOAT",
}
_SETTINGS_COLUMNS = {
    "last_market_context": "TEXT",
    "universe_mode": "TEXT",
    "auto_universe_size": "INTEGER",
    "auto_scan_enabled": "BOOLEAN",
    "auto_scan_time": "TEXT",
    "auto_scan_timezone": "TEXT",
    "auto_scan_days": "TEXT",
    "last_auto_run_date": "TEXT",
    "last_auto_run_at": "TIMESTAMP",
}

# ALTER TABLE ADD COLUMN leaves existing rows NULL, but the scheduler reads these
# on every tick. Backfill the singleton row so an upgraded DB behaves exactly like
# a freshly created one.
_SETTINGS_BACKFILL = {
    "auto_scan_enabled": False,
    "auto_scan_time": DEFAULT_AUTO_SCAN_TIME,
    "auto_scan_timezone": DEFAULT_AUTO_SCAN_TIMEZONE,
    "auto_scan_days": DEFAULT_AUTO_SCAN_DAYS,
}

_schema_ready = False


def ensure_schema() -> None:
    """Add any missing columns introduced by the upgrade (idempotent)."""
    global _schema_ready
    if _schema_ready:
        return
    try:
        inspector = sa_inspect(engine)
        tables = inspector.get_table_names()
        plans = [
            ("breakout_scan_results", _RESULT_COLUMNS),
            ("breakout_scanner_settings", _SETTINGS_COLUMNS),
        ]
        added: set = set()
        with engine.begin() as conn:
            for table, columns in plans:
                if table not in tables:
                    continue  # create_all will build it fresh with all columns
                existing = {c["name"] for c in inspector.get_columns(table)}
                for name, sqltype in columns.items():
                    if name not in existing:
                        conn.execute(
                            text(f'ALTER TABLE {table} ADD COLUMN {name} {sqltype}')
                        )
                        added.add(name)
                        logger.info(f"Added column {table}.{name}")

            for name, value in _SETTINGS_BACKFILL.items():
                if name in added:
                    conn.execute(
                        text(
                            "UPDATE breakout_scanner_settings "
                            f"SET {name} = :value WHERE {name} IS NULL"
                        ),
                        {"value": value},
                    )
        _schema_ready = True
    except Exception as e:  # pragma: no cover - best-effort migration
        logger.warning(f"ensure_schema failed (continuing): {e}")


def get_or_create_settings(db) -> BreakoutScannerSettings:
    """Fetch the singleton settings row, creating it with defaults if missing."""
    ensure_schema()
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
        universe_mode=getattr(settings, "universe_mode", None) or "curated",
        auto_universe_size=getattr(settings, "auto_universe_size", None) or 300,
    )
    weights = settings.get_weights()
    if weights:
        config.weights = {**config.weights, **weights}
    return config


def _build_auto_universe(uw_provider, config: ScannerConfig, log) -> list:
    """Fetch the top optionable US equities from UW screener for auto-universe mode."""
    if uw_provider is None or not uw_provider.is_available():
        log.warning("Auto universe requested but UW provider is unavailable; falling back to curated list")
        return []
    try:
        symbols = uw_provider.stock_screener_universe(
            max_symbols=config.auto_universe_size,
            min_price=config.min_price,
        )
        log.info(f"Auto universe: {len(symbols)} symbols from UW screener")
        return symbols
    except Exception as e:
        log.warning(f"Auto universe fetch failed: {e}")
        return []


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
                volume_expansion=c.volume_expansion,
                pct_from_52wk_high=c.pct_from_52wk_high,
                pct_to_pivot=c.pct_to_pivot,
                iv_rank=c.iv_rank,
                implied_move=c.implied_move,
                iv_vs_realized=c.iv_vs_realized,
                net_call_premium=c.net_call_premium,
                bullish_flow_score=c.bullish_flow_score,
                gex_regime=c.gex_regime,
                gamma_wall=c.gamma_wall,
                max_pain=c.max_pain,
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
        ensure_schema()
        settings_row = get_or_create_settings(db)

        if not settings_row.enabled:
            msg = "Breakout scanner is disabled. Enable it in settings to run a scan."
            _set_status(db, settings_row, "error", msg)
            return {"status": "error", "message": msg}

        config = _build_config(settings_row)

        # Providers: prefer Alpaca daily bars (reliable, consistent with the rest
        # of the app); fall back to Yahoo when Alpaca keys are unavailable.
        app_settings = get_settings()
        price_provider = None
        if app_settings.ALPACA_API_KEY and app_settings.ALPACA_SECRET_KEY:
            alpaca_provider = AlpacaPriceProvider(
                app_settings.ALPACA_API_KEY, app_settings.ALPACA_SECRET_KEY
            )
            if alpaca_provider.is_available():
                price_provider = alpaca_provider
        # Indices/^VIX for market context always come from Yahoo (Alpaca can't
        # supply ^VIX). When Yahoo is already the universe provider, reuse it.
        index_provider = None
        if price_provider is None:
            price_provider = YahooPriceProvider()
            logger.info("Breakout scan using Yahoo price provider")
        else:
            index_provider = YahooPriceProvider()
            logger.info("Breakout scan using Alpaca price provider (Yahoo for indices/VIX)")
        uw_provider = None
        if config.use_unusual_whales:
            uw_key = get_settings().UNUSUAL_WHALES_API_KEY
            if uw_key:
                # ~5 req/s spacing smooths bursts and reduces 429s during the
                # per-ticker deep-dive pass.
                uw_provider = UnusualWhalesProvider(api_key=uw_key, min_interval=0.2)
            else:
                logger.warning("use_unusual_whales is on but UNUSUAL_WHALES_API_KEY is not set")

        # Determine scan universe: auto mode fetches top optionable names from UW;
        # curated tickers are always merged in (and are the sole source in curated mode).
        curated = settings_row.get_universe_list()
        if config.universe_mode == "auto":
            auto_symbols = _build_auto_universe(uw_provider, config, logger)
            # Auto symbols first (ranked by options volume); curated appended for guaranteed inclusion
            universe = list(dict.fromkeys(auto_symbols + curated))
            if not universe:
                _set_status(
                    db, settings_row, "error",
                    "Auto universe is empty. Configure UW API key or add curated tickers.",
                )
                if uw_provider is not None:
                    uw_provider.close()
                return {"status": "error", "message": "Auto universe is empty"}
        else:
            universe = curated
            if not universe:
                _set_status(db, settings_row, "error", "Scan universe is empty. Add tickers first.")
                if uw_provider is not None:
                    uw_provider.close()
                return {"status": "error", "message": "Scan universe is empty"}

        _set_status(db, settings_row, "running", "Scan in progress...")

        result = run_scan(
            tickers=universe,
            config=config,
            price_provider=price_provider,
            uw_provider=uw_provider,
            index_provider=index_provider,
            logger=logger,
        )

        if uw_provider is not None:
            uw_provider.close()

        _persist_results(db, result)
        _publish_trade_idea(db, result.top_symbols)

        # Persist the market-context snapshot for the admin UI.
        try:
            settings_row.last_market_context = json.dumps(result.market_context or {})
        except (TypeError, ValueError):
            settings_row.last_market_context = None

        regime = (result.market_context or {}).get("regime")
        msg = (
            f"Scanned {result.scanned}/{result.universe_size} tickers, "
            f"published {len(result.candidates)} picks"
            + (" (UW active)" if result.used_unusual_whales else " (no UW)")
            + (f" | regime: {regime}" if regime else "")
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
