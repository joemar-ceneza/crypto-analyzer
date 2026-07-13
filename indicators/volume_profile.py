"""
Volume Profile: POC, Value Area (VAH/VAL), HVN and LVN detection.

The profile distributes each candle's volume across the price bins its
high-low range covers, building a horizontal volume histogram.

Public API:
    run_volume_profile(candles) -> dict with poc/vah/val/hvn/lvn + histogram
"""

import logging

import numpy as np
import pandas as pd

import config


# ======================================================
# HISTOGRAM CONSTRUCTION
# ======================================================
def _build_histogram(candles: pd.DataFrame, bins: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Builds the volume-by-price histogram.
    Each candle's volume is spread evenly across every bin its
    high-low range overlaps. Returns (bin_centers, bin_volumes).
    """
    price_min = float(candles["low"].min())
    price_max = float(candles["high"].max())
    if price_max <= price_min:
        # Degenerate case: flat price — one bin holds everything
        return np.array([price_min]), np.array([float(candles["volume"].sum())])

    edges = np.linspace(price_min, price_max, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    volumes = np.zeros(bins)

    lows = candles["low"].to_numpy()
    highs = candles["high"].to_numpy()
    candle_volumes = candles["volume"].to_numpy()

    for low, high, volume in zip(lows, highs, candle_volumes):
        first_bin = int(np.searchsorted(edges, low, side="right")) - 1
        last_bin = int(np.searchsorted(edges, high, side="left"))
        first_bin = max(first_bin, 0)
        last_bin = min(last_bin, bins)
        span = max(last_bin - first_bin, 1)
        volumes[first_bin:first_bin + span] += volume / span

    return centers, volumes


# ======================================================
# VALUE AREA
# ======================================================
def _find_value_area(
    centers: np.ndarray, volumes: np.ndarray, coverage: float
) -> tuple[float, float, float]:
    """
    Finds POC (highest-volume bin) and expands outward until `coverage`
    of total volume is inside the area. Returns (poc, vah, val).
    Standard market-profile expansion: at each step add the neighbouring
    bin (above or below) with the larger volume.
    """
    poc_index = int(np.argmax(volumes))
    total_volume = float(volumes.sum())
    target = total_volume * coverage

    low_index = high_index = poc_index
    covered = float(volumes[poc_index])

    while covered < target and (low_index > 0 or high_index < len(volumes) - 1):
        below = volumes[low_index - 1] if low_index > 0 else -1.0
        above = volumes[high_index + 1] if high_index < len(volumes) - 1 else -1.0
        if above >= below:
            high_index += 1
            covered += float(volumes[high_index])
        else:
            low_index -= 1
            covered += float(volumes[low_index])

    return float(centers[poc_index]), float(centers[high_index]), float(centers[low_index])


# ======================================================
# HVN / LVN DETECTION
# ======================================================
def _find_volume_nodes(centers: np.ndarray, volumes: np.ndarray) -> tuple[list[float], list[float]]:
    """
    High Volume Nodes: local maxima with volume > HVN_THRESHOLD x mean.
    Low Volume Nodes: local minima with volume < LVN_THRESHOLD x mean.
    Returns (hvn_prices, lvn_prices).
    """
    mean_volume = float(volumes.mean()) if len(volumes) else 0.0
    hvn: list[float] = []
    lvn: list[float] = []

    for i in range(1, len(volumes) - 1):
        is_local_max = volumes[i] >= volumes[i - 1] and volumes[i] >= volumes[i + 1]
        is_local_min = volumes[i] <= volumes[i - 1] and volumes[i] <= volumes[i + 1]
        if is_local_max and volumes[i] > mean_volume * config.HVN_THRESHOLD:
            hvn.append(float(centers[i]))
        elif is_local_min and volumes[i] < mean_volume * config.LVN_THRESHOLD:
            lvn.append(float(centers[i]))

    return hvn, lvn


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_volume_profile(candles: pd.DataFrame, log_result: bool = True) -> dict:
    """
    Builds the volume profile over the configured lookback window.
    `log_result=False` silences the info log (used by the backtester's
    trailing recomputation loop).

    Returns a dict:
        poc: Point of Control price
        vah / val: Value Area High / Low
        hvn / lvn: lists of High / Low Volume Node prices
        histogram: DataFrame(price, volume) for chart rendering
        price_vs_poc: "above" | "below" | "at"
        inside_value_area: True when price is between VAL and VAH
    """
    window = candles.tail(config.VOLUME_PROFILE_LOOKBACK)
    centers, volumes = _build_histogram(window, config.VOLUME_PROFILE_BINS)
    poc, vah, val = _find_value_area(centers, volumes, config.VALUE_AREA_PCT)
    hvn, lvn = _find_volume_nodes(centers, volumes)

    price = float(candles["close"].iloc[-1])
    tolerance = price * 0.001
    if price > poc + tolerance:
        price_vs_poc = "above"
    elif price < poc - tolerance:
        price_vs_poc = "below"
    else:
        price_vs_poc = "at"

    result = {
        "poc": poc,
        "vah": vah,
        "val": val,
        "hvn": hvn,
        "lvn": lvn,
        "histogram": pd.DataFrame({"price": centers, "volume": volumes}),
        "price_vs_poc": price_vs_poc,
        "inside_value_area": bool(val <= price <= vah),
    }
    if log_result:
        logging.info(
            "Volume profile: POC %.2f | VAH %.2f | VAL %.2f | price %s POC",
            poc, vah, val, price_vs_poc,
        )
    return result
