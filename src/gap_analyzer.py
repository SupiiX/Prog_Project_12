import numpy as np
from scipy.ndimage import label, center_of_mass
from shapely.ops import unary_union
from shapely.geometry import box

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import EARTH_RADIUS_M


def analyze_gaps(coverage: np.ndarray, grid_lat: np.ndarray, grid_lon: np.ndarray) -> dict:
    H, W = coverage.shape

    gap_mask         = coverage == 0
    overlap_mask     = coverage >= 2
    well_served_mask = coverage == 1

    center_lat = grid_lat.mean()
    dlat_deg = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon_deg = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)

    dlat_m = dlat_deg * EARTH_RADIUS_M * np.pi / 180
    dlon_m = dlon_deg * EARTH_RADIUS_M * np.pi / 180 * np.cos(np.radians(center_lat))
    cell_area_km2 = (dlat_m * dlon_m) / 1e6

    total_cells = H * W
    gap_cells     = int(gap_mask.sum())
    overlap_cells = int(overlap_mask.sum())

    return {
        'gap_mask':          gap_mask,
        'overlap_mask':      overlap_mask,
        'well_served_mask':  well_served_mask,
        'gap_cells':         gap_cells,
        'gap_area_km2':      gap_cells * cell_area_km2,
        'gap_fraction':      gap_cells / total_cells,
        'overlap_cells':     overlap_cells,
        'overlap_area_km2':  overlap_cells * cell_area_km2,
        'overlap_fraction':  overlap_cells / total_cells,
        'mean_coverage':     float(coverage.mean()),
        'max_coverage':      int(coverage.max()),
        'cell_area_km2':     cell_area_km2,
        'total_area_km2':    total_cells * cell_area_km2,
    }


def find_gap_clusters(gap_mask: np.ndarray, grid_lat: np.ndarray, grid_lon: np.ndarray, top_n: int = 10) -> list:
    labeled_array, num_features = label(gap_mask)
    if num_features == 0:
        return []

    # Vektorizalt: np.bincount adja az osszes region meretet egy menetben O(H*W)
    sizes = np.bincount(labeled_array.ravel())[1:]  # index 0 = hatter

    # center_of_mass egyszerre az osszes region-re - sokkal gyorsabb mint egyenkent
    region_ids = list(range(1, num_features + 1))
    centroids = center_of_mass(gap_mask, labeled_array, region_ids)

    H, W = grid_lat.shape
    clusters = []
    for i, (cy, cx) in enumerate(centroids):
        ci = min(max(int(round(cy)), 0), H - 1)
        cj = min(max(int(round(cx)), 0), W - 1)
        clusters.append({
            'lat':        float(grid_lat[ci, cj]),
            'lon':        float(grid_lon[ci, cj]),
            'size_cells': int(sizes[i]),
        })

    clusters.sort(key=lambda x: -x['size_cells'])
    return clusters[:top_n]


def compute_gap_polygons(gap_mask: np.ndarray, grid_lat: np.ndarray, grid_lon: np.ndarray):
    H, W = gap_mask.shape
    dlat = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)

    # Adaptiv lepeskoz: max ~1500 box, unary_union mindig gyors marad
    gap_count = int(gap_mask.sum())
    step = max(10, int(np.sqrt(gap_count / 1500))) if gap_count > 0 else 10

    boxes = []
    for i in range(0, H, step):
        for j in range(0, W, step):
            if gap_mask[i, j]:
                lat = grid_lat[i, j]
                lon = grid_lon[i, j]
                boxes.append(box(lon - dlon/2, lat - dlat/2,
                                 lon + dlon/2, lat + dlat/2))
    if not boxes:
        return None
    return unary_union(boxes)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import BBOX
    from src.rasterizer import create_grid

    print("Smoke test: gap_analyzer")

    grid_lat, grid_lon = create_grid(BBOX, 50)
    fake_coverage = np.zeros((50, 50), dtype=np.int16)
    fake_coverage[10:20, 10:20] = 1
    fake_coverage[30:40, 30:40] = 3

    stats = analyze_gaps(fake_coverage, grid_lat, grid_lon)
    print(f"  Gap fraction: {stats['gap_fraction']:.2%}")
    print(f"  Gap area: {stats['gap_area_km2']:.2f} km2")
    print(f"  Overlap fraction: {stats['overlap_fraction']:.2%}")

    clusters = find_gap_clusters(stats['gap_mask'], grid_lat, grid_lon, top_n=5)
    print(f"  Gap clusters found: {len(clusters)}")

    poly = compute_gap_polygons(stats['gap_mask'], grid_lat, grid_lon)
    print(f"  Gap polygon area (deg2): {poly.area:.6f}" if poly else "  No gap polygon")
    print("OK")
