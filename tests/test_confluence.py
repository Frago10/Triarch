"""Tests del filtro de confluencia."""
from __future__ import annotations

import pytest

from confluence.filter import ConfluenceConfig, ConfluenceFilter
from signals.schema import Confidence, Direction, Signal


def _sig(strategy: str, family: str, direction: Direction, score: float = 0.6) -> Signal:
    return Signal(
        symbol="XAUUSD",
        timeframe="M15",
        strategy=strategy,
        family=family,
        direction=direction,
        entry=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
        take_profit_2=2015.0,
        score=score,
        confidence=Confidence.MEDIUM,
        risk_pts=5.0,
        reward_pts_tp1=10.0,
        rr_ratio=2.0,
    )


def test_passthrough_with_lenient_config():
    f = ConfluenceFilter(ConfluenceConfig(min_signals=1, min_families=1, min_combined_score=0.0))
    d = f.filter([_sig("ORB", "opening", Direction.LONG)])
    assert d.accepted
    assert d.chosen_signal is not None


def test_rejects_single_signal_with_strict_config():
    f = ConfluenceFilter(ConfluenceConfig(min_signals=2, min_families=2, min_combined_score=1.0))
    d = f.filter([_sig("ORB", "opening", Direction.LONG, score=0.7)])
    assert not d.accepted
    assert "min_signals" in d.reason


def test_rejects_two_signals_same_family():
    """2 señales pero misma familia → rechaza por min_families."""
    f = ConfluenceFilter(ConfluenceConfig(min_signals=2, min_families=2, min_combined_score=0.0))
    d = f.filter(
        [
            _sig("ORB", "opening", Direction.LONG, score=0.6),
            _sig("ORB_RETEST", "opening", Direction.LONG, score=0.6),
        ]
    )
    assert not d.accepted
    assert "min_families" in d.reason


def test_accepts_two_signals_two_families():
    f = ConfluenceFilter(ConfluenceConfig(min_signals=2, min_families=2, min_combined_score=1.0))
    d = f.filter(
        [
            _sig("ORB", "opening", Direction.LONG, score=0.6),
            _sig("EMA_MOMENTUM", "trend", Direction.LONG, score=0.7),
        ]
    )
    assert d.accepted
    assert d.chosen_signal.strategy == "EMA_MOMENTUM"  # mayor score


def test_rejects_direction_tie():
    f = ConfluenceFilter(ConfluenceConfig(min_signals=1, min_families=1, min_combined_score=0.0))
    d = f.filter(
        [
            _sig("ORB", "opening", Direction.LONG, score=0.6),
            _sig("VWAP_MR", "mean", Direction.SHORT, score=0.7),
        ]
    )
    assert not d.accepted
    assert "direction_tie" in d.reason


def test_rejects_low_combined_score():
    f = ConfluenceFilter(ConfluenceConfig(min_signals=2, min_families=2, min_combined_score=2.0))
    d = f.filter(
        [
            _sig("ORB", "opening", Direction.LONG, score=0.4),
            _sig("EMA_MOMENTUM", "trend", Direction.LONG, score=0.4),
        ]
    )
    assert not d.accepted
    assert "score" in d.reason
