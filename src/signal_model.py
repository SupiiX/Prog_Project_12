import numpy as np
import pandas as pd
from shapely.geometry import Point

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import (
    DEFAULT_RADII_M, MAX_RADIUS_M, MIN_RADIUS_M,
    TX_POWER_DBM, PATH_LOSS_EXPONENT, REF_DISTANCE_M,
    FREQ_MHZ, EARTH_RADIUS_M,
)


def _path_loss_radius_vectorized(signal_series: pd.Series, radio_series: pd.Series) -> pd.Series:
    freq_hz = radio_series.map(FREQ_MHZ).fillna(1800) * 1e6
    pl_d0 = (20 * np.log10(REF_DISTANCE_M) +
             20 * np.log10(freq_hz) - 147.55)
    exponent = (TX_POWER_DBM - signal_series - pl_d0) / (10 * PATH_LOSS_EXPONENT)
    radii = REF_DISTANCE_M * np.power(10.0, exponent)
    return radii.clip(lower=MIN_RADIUS_M, upper=MAX_RADIUS_M)


def estimate_radii(df: pd.DataFrame) -> pd.Series:
    # Prioritás 3: default (alap)
    radii = df['radio'].map(DEFAULT_RADII_M).fillna(500.0).astype(float)

    # Prioritás 2: signal-alapú (felülírja ahol van jel)
    sig_mask = df['averageSignal'] != 0
    if sig_mask.any():
        radii[sig_mask] = _path_loss_radius_vectorized(
            df.loc[sig_mask, 'averageSignal'],
            df.loc[sig_mask, 'radio']
        )

    # Prioritás 1: range mező (felülírja ahol érvényes)
    range_mask = (df['range'] > 0) & (df['range'] < MAX_RADIUS_M * 3)
    radii[range_mask] = df.loc[range_mask, 'range'].clip(upper=MAX_RADIUS_M)

    return radii.clip(lower=MIN_RADIUS_M, upper=MAX_RADIUS_M)


def add_shapely_geometries(df: pd.DataFrame) -> pd.DataFrame:
    R = EARTH_RADIUS_M
    df = df.copy()
    df['radius_deg'] = df['radius'] / (R * np.pi / 180)

    # Lista-comprehension: 3-5x gyorsabb mint df.apply() row-wise Python loop
    df['geometry'] = [
        Point(lon, lat).buffer(r)
        for lon, lat, r in zip(df['lon'], df['lat'], df['radius_deg'])
    ]
    return df


if __name__ == '__main__':
    print("Smoke test: signal_model")

    test_df = pd.DataFrame({
        'radio':         ['GSM', 'LTE', 'NR', 'UMTS', 'LTE'],
        'averageSignal': [0,     -85,   -70,  0,      -95],
        'range':         [0,     0,     0,    800,    0],
        'lat':           [47.5,  47.5,  47.5, 47.5,   47.5],
        'lon':           [19.0,  19.0,  19.0, 19.0,   19.0],
    })

    radii = estimate_radii(test_df)
    print(f"  Radii: {radii.values}")
    assert (radii >= MIN_RADIUS_M).all(), "Min radius violated"
    assert (radii <= MAX_RADIUS_M).all(), "Max radius violated"

    test_df['radius'] = radii
    test_df = add_shapely_geometries(test_df)
    print(f"  Geometry types: {test_df['geometry'].apply(type).unique()}")
    assert 'geometry' in test_df.columns
    print("OK")
