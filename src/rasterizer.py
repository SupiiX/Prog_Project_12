import numpy as np
import pandas as pd
from tqdm import tqdm

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import EARTH_RADIUS_M, BBOX, GRID_RESOLUTION


def create_grid(bbox: dict, resolution: int):
    lats = np.linspace(bbox['lat_min'], bbox['lat_max'], resolution)
    lons = np.linspace(bbox['lon_min'], bbox['lon_max'], resolution)
    grid_lat, grid_lon = np.meshgrid(lats, lons, indexing='ij')
    return grid_lat, grid_lon


def rasterize_coverage(towers_df: pd.DataFrame, grid_lat: np.ndarray, grid_lon: np.ndarray) -> np.ndarray:
    H, W = grid_lat.shape
    coverage = np.zeros((H, W), dtype=np.int16)

    dlat = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)
    lat0 = grid_lat[0, 0]
    lon0 = grid_lon[0, 0]

    R = EARTH_RADIUS_M
    _R_pi_180 = R * np.pi / 180   # loop-on kivul egyszer szamolva

    # itertuples: 5-10x gyorsabb mint iterrows (nem keszit Series-t soronkent)
    for tower in tqdm(towers_df.itertuples(index=False), total=len(towers_df),
                      desc="Rasterizing"):
        r    = tower.radius
        tlat = tower.lat
        tlon = tower.lon
        cos_lat = np.cos(np.radians(tlat))   # ketto helyen is kell, egyszer szamolva

        r_lat_deg = r / _R_pi_180
        r_lon_deg = r / (_R_pi_180 * cos_lat)

        lat_lo = max(0, int((tlat - r_lat_deg - lat0) / dlat))
        lat_hi = min(H, int((tlat + r_lat_deg - lat0) / dlat) + 2)
        lon_lo = max(0, int((tlon - r_lon_deg - lon0) / dlon))
        lon_hi = min(W, int((tlon + r_lon_deg - lon0) / dlon) + 2)

        sub_lat = grid_lat[lat_lo:lat_hi, lon_lo:lon_hi]
        sub_lon = grid_lon[lat_lo:lat_hi, lon_lo:lon_hi]

        dlat_m = (sub_lat - tlat) * _R_pi_180
        dlon_m = (sub_lon - tlon) * _R_pi_180 * cos_lat
        dist_m = np.sqrt(dlat_m**2 + dlon_m**2)

        coverage[lat_lo:lat_hi, lon_lo:lon_hi] += (dist_m <= r).astype(np.int16)

    return coverage


if __name__ == '__main__':
    print("Smoke test: rasterizer")

    test_towers = pd.DataFrame({
        'lat':    [47.5,   47.52,  47.48],
        'lon':    [19.0,   19.05,  18.95],
        'radius': [500.0,  300.0,  800.0],
    })

    grid_lat, grid_lon = create_grid(BBOX, 100)
    cov = rasterize_coverage(test_towers, grid_lat, grid_lon)
    print(f"  Coverage max: {cov.max()}, gap fraction: {(cov == 0).mean():.2%}")
    assert cov.max() >= 1, "At least one cell must be covered!"
    assert grid_lat.shape == (100, 100)
    print("OK")
