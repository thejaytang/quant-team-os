"""Deterministic pandas-based factor and strategy analytics.

This module turns the factor/strategy tear-sheet activities from placeholder
generators into real computations whenever OHLCV rows are available in the
workflow payload. It intentionally avoids heavyweight research libraries so
it can run inside every worker image and in local tests.

Method (``pandas_ic_v1``):

- factor: cross-sectional price momentum over ``lookback`` bars.
- forward return: next-bar close-to-close return per symbol.
- IC: Spearman rank correlation between factor and forward return, computed
  cross-sectionally per date when enough symbols exist, otherwise pooled.
- strategy proxy: equal-weight long portfolio of the top factor quantile,
  rebalanced every bar, used for Sharpe / drawdown / turnover diagnostics.

These numbers are honest small-scale statistics of the supplied rows. They
carry evidence grade ``verified`` only when the rows themselves came from a
real ingestion (``rows_provenance == "user_supplied"``), otherwise the
artifacts stay ``sample`` graded.
"""

from __future__ import annotations

import math
from typing import Any

MIN_ROWS_FOR_ANALYSIS = 6
ANNUALIZATION_FACTOR = 252


def analyze_factor_rows(rows: list[dict[str, Any]], lookback: int = 3) -> dict[str, Any] | None:
    """Compute IC and quantile diagnostics from OHLCV rows.

    Returns ``None`` when rows are insufficient for a meaningful statistic.
    """
    frame = _prices_frame(rows)
    if frame is None:
        return None
    import pandas as pd

    factor = frame["close"].groupby(level="symbol").pct_change(lookback)
    forward = frame["close"].groupby(level="symbol").pct_change().groupby(level="symbol").shift(-1)
    joined = pd.DataFrame({"factor": factor, "forward": forward}).dropna()
    if len(joined) < 3:
        return None

    per_date_ic = []
    for _, group in joined.groupby(level="date"):
        if len(group) >= 3:
            value = _spearman(group["factor"], group["forward"])
            if value is not None:
                per_date_ic.append(value)
    if per_date_ic:
        ic = float(sum(per_date_ic) / len(per_date_ic))
        ic_mode = "cross_sectional"
    else:
        pooled = _spearman(joined["factor"], joined["forward"])
        if pooled is None:
            return None
        ic = pooled
        ic_mode = "pooled_time_series"

    ic_std = float(pd.Series(per_date_ic).std(ddof=0)) if len(per_date_ic) >= 2 else None
    icir = float(ic / ic_std) if ic_std else None

    quantiles = _quantile_returns(joined)
    return {
        "method": "pandas_ic_v1",
        "lookback": lookback,
        "observations": len(joined),
        "ic": round(ic, 6),
        "ic_mode": ic_mode,
        "icir": round(icir, 6) if icir is not None else None,
        "quantile_forward_returns": quantiles,
    }


def compute_strategy_metrics(rows: list[dict[str, Any]], lookback: int = 3) -> dict[str, Any] | None:
    """Compute Sharpe / drawdown / turnover for a top-quantile momentum proxy."""
    frame = _prices_frame(rows)
    if frame is None:
        return None
    import pandas as pd

    closes = frame["close"].unstack(level="symbol").sort_index()
    if closes.shape[0] < MIN_ROWS_FOR_ANALYSIS:
        return None
    returns = closes.pct_change()
    factor = closes.pct_change(lookback)

    weights = []
    for date_index in closes.index:
        scores = factor.loc[date_index].dropna()
        if scores.empty:
            weights.append(pd.Series(dtype=float))
            continue
        cutoff = scores.quantile(0.5)
        selected = scores[scores >= cutoff]
        weights.append(pd.Series(1.0 / len(selected), index=selected.index) if len(selected) else pd.Series(dtype=float))
    weight_frame = pd.DataFrame(weights, index=closes.index).fillna(0.0)

    held = weight_frame.shift(1).fillna(0.0)
    portfolio_returns = (held * returns).sum(axis=1).iloc[1:]
    if portfolio_returns.empty or portfolio_returns.std(ddof=0) == 0:
        return None

    daily_mean = float(portfolio_returns.mean())
    daily_std = float(portfolio_returns.std(ddof=0))
    sharpe = daily_mean / daily_std * math.sqrt(ANNUALIZATION_FACTOR)

    equity = (1 + portfolio_returns).cumprod()
    drawdown = float((equity / equity.cummax() - 1).min())

    turnover = float((weight_frame - held).abs().sum(axis=1).iloc[1:].mean() / 2)
    trade_count = int(((weight_frame - held).abs() > 1e-12).sum().sum())

    return {
        "method": "pandas_ic_v1",
        "observations": len(portfolio_returns),
        "sharpe": round(sharpe, 6),
        "max_drawdown": round(abs(drawdown), 6),
        "turnover_daily": round(turnover, 6),
        "trade_count": trade_count,
        "cumulative_return": round(float(equity.iloc[-1] - 1), 6),
    }


def _spearman(left, right) -> float | None:
    """Spearman rank correlation without a scipy dependency.

    Pearson correlation of ranks equals Spearman correlation.
    """
    value = left.rank().corr(right.rank())
    if value is None or math.isnan(value):
        return None
    return float(value)


def _prices_frame(rows: list[dict[str, Any]]):
    if not rows or len(rows) < MIN_ROWS_FOR_ANALYSIS:
        return None
    import pandas as pd

    records = []
    for row in rows:
        symbol = row.get("symbol")
        date_value = row.get("date") or row.get("timestamp")
        close = row.get("close")
        if symbol is None or date_value is None or close is None:
            continue
        try:
            records.append({"symbol": str(symbol), "date": str(date_value), "close": float(close)})
        except (TypeError, ValueError):
            continue
    if len(records) < MIN_ROWS_FOR_ANALYSIS:
        return None
    frame = pd.DataFrame(records).drop_duplicates(subset=["symbol", "date"]).set_index(["symbol", "date"]).sort_index()
    if frame.empty:
        return None
    return frame


def _quantile_returns(joined) -> dict[str, float]:
    import pandas as pd

    try:
        buckets = pd.qcut(joined["factor"], q=min(3, max(2, len(joined) // 3)), labels=False, duplicates="drop")
    except ValueError:
        return {}
    grouped = joined.groupby(buckets)["forward"].mean()
    return {f"q{int(bucket) + 1}": round(float(value), 6) for bucket, value in grouped.items() if not math.isnan(value)}
