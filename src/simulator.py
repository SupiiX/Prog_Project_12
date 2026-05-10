import numpy as np

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import EARTH_RADIUS_M, DEFAULT_RADII_M


def generate_hypothetical_towers(clusters: list, towers_df) -> list:
    new_towers = []
    for i, cluster in enumerate(clusters[:5]):
        new_towers.append({
            'lat':    cluster['lat'],
            'lon':    cluster['lon'],
            'radius': DEFAULT_RADII_M['LTE'],
            'radio':  'LTE',
            'label':  f"Hipotetikus #{i + 1}",
        })
    return new_towers


def _add_tower_to_grid(coverage: np.ndarray, grid_lat: np.ndarray, grid_lon: np.ndarray,
                        tlat: float, tlon: float, radius: float) -> None:
    H, W = grid_lat.shape
    R = EARTH_RADIUS_M
    dlat = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)
    lat0, lon0 = grid_lat[0, 0], grid_lon[0, 0]

    r_lat_deg = radius / (R * np.pi / 180)
    r_lon_deg = radius / (R * np.pi / 180 * np.cos(np.radians(tlat)))

    lat_lo = max(0, int((tlat - r_lat_deg - lat0) / dlat))
    lat_hi = min(H, int((tlat + r_lat_deg - lat0) / dlat) + 2)
    lon_lo = max(0, int((tlon - r_lon_deg - lon0) / dlon))
    lon_hi = min(W, int((tlon + r_lon_deg - lon0) / dlon) + 2)

    sub_lat = grid_lat[lat_lo:lat_hi, lon_lo:lon_hi]
    sub_lon = grid_lon[lat_lo:lat_hi, lon_lo:lon_hi]
    dlat_m = (sub_lat - tlat) * R * np.pi / 180
    dlon_m = (sub_lon - tlon) * R * np.pi / 180 * np.cos(np.radians(tlat))
    dist_m = np.sqrt(dlat_m**2 + dlon_m**2)
    coverage[lat_lo:lat_hi, lon_lo:lon_hi] += (dist_m <= radius).astype(np.int16)


def _per_tower_standalone_gap_reduction(coverage: np.ndarray, grid_lat: np.ndarray,
                                         grid_lon: np.ndarray, new_towers: list,
                                         cell_area_km2: float) -> list:
    """
    For each new tower, compute the gap-area (km²) it would close if placed alone.
    Independent metric - diagnostic ranking that does NOT sum to the total
    (overlaps are double-counted), but tells you which placements pull weight.
    """
    contribs = []
    for tower in new_towers:
        scratch = coverage.copy()
        _add_tower_to_grid(scratch, grid_lat, grid_lon,
                           tower['lat'], tower['lon'], tower['radius'])
        gap_fixed_cells = int(((coverage == 0) & (scratch >= 1)).sum())
        contribs.append(gap_fixed_cells * cell_area_km2)
    return contribs


def simulate_new_towers(coverage: np.ndarray, grid_lat: np.ndarray, grid_lon: np.ndarray,
                         new_towers: list, original_stats: dict) -> dict:
    new_coverage = coverage.copy()

    for tower in new_towers:
        _add_tower_to_grid(new_coverage, grid_lat, grid_lon,
                           tower['lat'], tower['lon'], tower['radius'])

    from src.gap_analyzer import analyze_gaps
    new_stats = analyze_gaps(new_coverage, grid_lat, grid_lon)

    gap_delta = original_stats['gap_area_km2'] - new_stats['gap_area_km2']
    gap_pct   = gap_delta / original_stats['gap_area_km2'] * 100 if original_stats['gap_area_km2'] > 0 else 0.0

    per_tower = _per_tower_standalone_gap_reduction(
        coverage, grid_lat, grid_lon, new_towers,
        original_stats['cell_area_km2'],
    )

    return {
        'before':                  original_stats,
        'after':                   new_stats,
        'new_towers':              new_towers,
        'gap_reduction_km2':       gap_delta,
        'gap_reduction_pct':       gap_pct,
        'original_grid':           coverage,
        'new_coverage_grid':       new_coverage,
        'per_tower_contribution':  per_tower,
    }


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import BBOX
    from src.rasterizer import create_grid
    from src.gap_analyzer import analyze_gaps, find_gap_clusters

    print("Smoke test: simulator")

    grid_lat, grid_lon = create_grid(BBOX, 50)
    fake_coverage = np.zeros((50, 50), dtype=np.int16)
    fake_coverage[10:40, 10:40] = 1

    stats = analyze_gaps(fake_coverage, grid_lat, grid_lon)
    clusters = find_gap_clusters(stats['gap_mask'], grid_lat, grid_lon, top_n=5)
    print(f"  Gap clusters: {len(clusters)}")

    new_towers = generate_hypothetical_towers(clusters, None)
    print(f"  Hypothetical towers: {len(new_towers)}")

    sim = simulate_new_towers(fake_coverage, grid_lat, grid_lon, new_towers, stats)
    print(f"  Gap reduction: {sim['gap_reduction_km2']:.4f} km2  ({sim['gap_reduction_pct']:.1f}%)")
    assert sim['gap_reduction_km2'] >= 0
    print("OK")
