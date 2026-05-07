#!/usr/bin/env python3
"""
Project 12: Mobile Tower Coverage Mapper
Entry point - runs the whole pipeline end-to-end.
"""
import os
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')  # GUI nelkuli backend - headless modban szukseges

# UTF-8 kimenet Windows terminalon
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from config import (
    BBOX, CITY, MCC, GRID_RESOLUTION,
    RAW_DATA_PATH, PROCESSED_PATH, COVERAGE_GRID_PATH,
    OUTPUT_MAP_HTML, OUTPUT_HEATMAP_PNG, OUTPUT_SIM_PNG,
    MANUAL_NEW_TOWERS,
)
from src.data_loader import load_towers, clean_towers, save_processed
from src.signal_model import estimate_radii, add_shapely_geometries
from src.rasterizer import create_grid, rasterize_coverage
from src.gap_analyzer import analyze_gaps, find_gap_clusters, compute_gap_polygons
from src.visualizer import (
    create_folium_map,
    create_heatmap_figure,
    create_simulation_figure,
)
from src.simulator import generate_hypothetical_towers, simulate_new_towers


def main():
    for d in ['data/raw', 'data/processed', 'output']:
        os.makedirs(d, exist_ok=True)

    print("=" * 55)
    print("  Project 12 - Mobile Tower Coverage Mapper")
    print("=" * 55)

    # --- 1. Adatbetoltes ---
    print("\n[1/5] Loading data...")
    towers = load_towers(RAW_DATA_PATH, BBOX, MCC)
    towers = clean_towers(towers)
    print(f"  [OK] Loaded {len(towers):,} towers in {CITY}")
    print(f"  Radio types: {towers['radio'].value_counts().to_dict()}")

    # --- 2. Sugar becsles ---
    print("\n[2/5] Estimating coverage radii...")
    towers['radius'] = estimate_radii(towers)
    print(f"  [OK] Radius: min={towers['radius'].min():.0f}m, "
          f"max={towers['radius'].max():.0f}m, "
          f"mean={towers['radius'].mean():.0f}m")
    towers = add_shapely_geometries(towers)
    print(f"  [OK] Shapely geometries created: {len(towers)} circles")
    save_processed(towers.drop(columns=['geometry', 'radius_deg']), PROCESSED_PATH)

    # --- 3. Raszterizalas ---
    print(f"\n[3/5] Rasterizing ({GRID_RESOLUTION}x{GRID_RESOLUTION} grid)...")
    grid_lat, grid_lon = create_grid(BBOX, GRID_RESOLUTION)

    grid_is_fresh = (
        os.path.exists(COVERAGE_GRID_PATH) and
        os.path.exists(PROCESSED_PATH) and
        os.path.getmtime(COVERAGE_GRID_PATH) >= os.path.getmtime(PROCESSED_PATH)
    )
    if grid_is_fresh:
        print("  -> Cache hit, loading...")
        coverage = np.load(COVERAGE_GRID_PATH)
    else:
        coverage = rasterize_coverage(towers, grid_lat, grid_lon)
        np.save(COVERAGE_GRID_PATH, coverage)
    print(f"  [OK] Coverage grid ready. Max: {coverage.max()} towers/cell")

    # --- 4. Gap analizis ---
    print("\n[4/5] Gap analysis...")
    stats = analyze_gaps(coverage, grid_lat, grid_lon)
    clusters = find_gap_clusters(stats['gap_mask'], grid_lat, grid_lon, top_n=10)
    print(f"  [OK] Coverage: {(1 - stats['gap_fraction']) * 100:.1f}%")
    print(f"  [OK] Gap area: {stats['gap_area_km2']:.1f} km2")
    print(f"  [OK] Overlap area: {stats['overlap_area_km2']:.1f} km2")
    print(f"  [OK] Largest gap clusters identified: {len(clusters)}")
    gap_poly = compute_gap_polygons(stats['gap_mask'], grid_lat, grid_lon)
    if gap_poly:
        print(f"  [OK] Gap MultiPolygon (shapely): {gap_poly.area * 1e10:.1f} km2 (deg-based)")

    # --- 5. Vizualizacio + szimulacio ---
    print("\n[5/5] Visualization & simulation...")
    import matplotlib.pyplot as plt

    fmap = create_folium_map(towers, coverage, grid_lat, grid_lon, stats)
    fmap.save(OUTPUT_MAP_HTML)
    print(f"  [OK] Interactive map: {OUTPUT_MAP_HTML}")

    fig = create_heatmap_figure(coverage, BBOX, stats, towers)
    fig.savefig(OUTPUT_HEATMAP_PNG, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  [OK] Heatmap: {OUTPUT_HEATMAP_PNG}")

    new_towers = (MANUAL_NEW_TOWERS if MANUAL_NEW_TOWERS
                  else generate_hypothetical_towers(clusters, towers))
    print(f"  -> Placing {len(new_towers)} hypothetical towers...")
    sim = simulate_new_towers(coverage, grid_lat, grid_lon, new_towers, stats)

    fig3 = create_simulation_figure(sim, grid_lat, grid_lon, BBOX)
    fig3.savefig(OUTPUT_SIM_PNG, dpi=150, bbox_inches='tight')
    plt.close(fig3)

    print(f"  [OK] Gap reduction: {sim['gap_reduction_km2']:.2f} km2 "
          f"({sim['gap_reduction_pct']:.1f}%)")
    print(f"  [OK] Simulation figure: {OUTPUT_SIM_PNG}")

    # --- Osszefoglalo ---
    print("\n" + "=" * 55)
    print("  DONE! Output files:")
    print(f"    {OUTPUT_MAP_HTML}   <- open in browser")
    print(f"    {OUTPUT_HEATMAP_PNG}")
    print(f"    {OUTPUT_SIM_PNG}")
    print("=" * 55)


if __name__ == '__main__':
    main()
