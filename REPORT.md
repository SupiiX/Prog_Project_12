# Project 12 – Mobile Tower Coverage Mapper
## Progress Report

**Student:** [name]  
**Subject:** Programming 2  
**Date:** 2026-05-09  

---

## 1. Project Overview

**Goal:** Analyse the mobile-cell coverage of Budapest using the freely available
[OpenCelliD](https://opencellid.org) crowd-sourced database.
The application loads raw tower data, estimates each tower's coverage radius,
rasterises the signal onto a 500 × 500 grid (~100 m resolution),
identifies uncovered (gap) areas, and simulates where new towers should be placed
to maximise coverage gain.

**Input data:** `data/raw/cell_towers.csv.gz` — OpenCelliD full Hungary export  
**Deliverables:**
| File | Description |
|------|-------------|
| `output/coverage_map.html` | Interactive Folium map (open in browser) |
| `output/heatmap.png` | Static 2-panel matplotlib heatmap |
| `output/gap_analysis.png` | Gap overlay + suggested new-tower locations |
| `output/simulation_report.png` | Before / after / difference 3-panel figure |

---

## 2. Project Structure

```
project_12/
├── app.py              ← Tkinter desktop GUI (4 tabs)
├── main.py             ← Headless CLI entry point
├── config.py           ← All constants (BBOX, radii, grid, paths)
├── requirements.txt
└── src/
    ├── data_loader.py  ← CSV loading (chunked), filtering, cleaning
    ├── signal_model.py ← Coverage-radius estimation (path-loss model + Shapely)
    ├── rasterizer.py   ← 500×500 coverage grid builder
    ├── gap_analyzer.py ← Gap detection, cluster labelling, Shapely MultiPolygon
    ├── visualizer.py   ← Folium map + matplotlib figures
    └── simulator.py    ← Hypothetical new-tower placement & evaluation
```

---

## 3. Pipeline Steps

### 3.1 Data Loading (`src/data_loader.py`)

The raw OpenCelliD CSV is ~600 MB uncompressed (Hungary-wide).
The loader reads it in **100 000-row chunks** so it never loads the whole file
into RAM at once. Each chunk is immediately filtered by:

* **MCC = 216** (Hungary country code)
* **Bounding box** lat 47.35–47.65 °N, lon 18.85–19.35 °E (Greater Budapest)

Cleaning steps applied afterwards:
- Drop rows with invalid coordinates
- Normalise unknown radio types to `LTE` (most common)
- Zero-fill missing `averageSignal` and `range` values
- Remove lat+lon+radio duplicates

Result: ~10 000–20 000 unique towers retained.

### 3.2 Coverage Radius Estimation (`src/signal_model.py`)

Each tower needs a single radius value (metres).
Three priority levels are evaluated **vectorised** (no Python loops):

| Priority | Source | Condition |
|----------|--------|-----------|
| 1 (best) | OpenCelliD `range` field | `0 < range < 3 × MAX_RADIUS` |
| 2 | Signal-based log-distance path-loss model | `averageSignal ≠ 0` |
| 3 (fallback) | Radio-type default (`GSM`=1000 m, `UMTS`=500 m, `LTE`=300 m, `NR`=150 m) | always |

**Path-loss formula** (log-distance model, ITU-R P.1411):

```
PL(d₀) = 20·log₁₀(d₀) + 20·log₁₀(f_Hz) − 147.55
d = d₀ · 10^((Pₜ − Pᵣ − PL(d₀)) / (10·n))
```

where `Pₜ = 43 dBm` (transmit power), `n = 3.5` (urban exponent),
`d₀ = 100 m` (reference distance).

After radius estimation, **Shapely** `Point.buffer()` is called for every tower,
producing a `geometry` column of circular Shapely polygons. This satisfies the
mandatory Shapely usage requirement and could be used for exact containment queries.

All radii are clipped to `[50 m, 1000 m]`.

### 3.3 Rasterisation (`src/rasterizer.py`)

A 500 × 500 NumPy `int16` grid covers Budapest.
Naïve approach (every tower × every cell) = 500 × 500 × 15 000 ≈ 3.75 billion
operations — too slow.

**Optimised algorithm:**
For each tower:
1. Convert radius to degrees (lat and lon, accounting for Earth's curvature).
2. Compute the **bounding-box** of candidate grid cells (4 index calculations).
3. Extract the sub-grid (typically ≤ 400 cells).
4. Compute **flat-earth distance** for each sub-cell (vectorised NumPy).
5. Increment `coverage[i, j]` wherever distance ≤ radius.

Additional micro-optimisations:
- `itertuples` instead of `iterrows` (5–10 × faster — avoids per-row Series creation)
- `cos(lat)` computed once per tower (not per sub-cell)
- `R · π/180` constant precomputed outside the loop

The grid is **cached** to `data/processed/coverage_grid.npy`; subsequent runs
reload it instantly (mtime comparison against the processed towers CSV).

### 3.4 Gap Analysis (`src/gap_analyzer.py`)

The coverage grid is thresholded:

| Category | Condition | Colour (heatmap) |
|----------|-----------|-----------------|
| Gap | `coverage == 0` | Red |
| Well-served | `coverage == 1` | Yellow |
| Overlap | `coverage >= 2` | Green |

**Connected-component labelling** (`scipy.ndimage.label`) groups gap pixels
into contiguous regions. The top 10 largest clusters are found by:

```python
sizes    = np.bincount(labeled_array.ravel())[1:]          # vectorised
centroids = center_of_mass(gap_mask, labeled_array, ids)   # batch call
```

These centroids become the suggested new-tower locations.

A **Shapely MultiPolygon** of the gap area is also produced (`unary_union` of
sampled cell boxes) — its `.area` attribute serves as an independent area check.

### 3.5 Visualisation (`src/visualizer.py`)

#### Folium interactive HTML map
- **RGBA raster overlay** (not HeatMap plugin): the 500 × 500 coverage array
  is converted to a RGBA image with log-scaled alpha and placed as a
  `folium.raster_layers.ImageOverlay`. This gives pixel-accurate, zoom-stable
  rendering (unlike the HeatMap plugin which produces blurry tiles).
- Gap area: red `CircleMarker` dots sampled every 5th row/column.
- Tower markers: coloured by radio type (GSM=blue, UMTS=orange, LTE=green, NR=purple).
  Up to 2000 randomly sampled when >5000 towers exist.

#### Matplotlib figures
1. **Heatmap** — 2 panels: coverage count (log-scale YlOrRd) + category map (RdYlGn_r).
   `contextily` adds OSM basemap tiles under both axes where available.
2. **Gap analysis** — single panel: coverage background + red gap overlay +
   yellow star markers for suggested tower locations.
3. **Simulation** — 3 panels: before / after / difference (green = newly covered cells).

All colorbars use `LogNorm` for the coverage axis. Alpha is also log-scaled so
sparsely covered suburbs stay nearly transparent while dense city centres show
full colour.

### 3.6 Simulation (`src/simulator.py`)

The top 5 gap cluster centroids are turned into hypothetical LTE towers
(radius = 300 m default). Their effect is calculated by adding them to a
**copy** of the coverage grid (same bounding-box algorithm as the rasteriser)
and calling `analyze_gaps` again on the result.

Output metrics:
- Gap reduction in km²
- Gap reduction as a percentage
- Before / after coverage percentages

---

## 4. Desktop GUI (`app.py`)

The application is a **Tkinter** desktop window with 4 tabs.

### Tab 1 — Live Map (tkintermapview)

- Uses the **`tkintermapview`** library (native Tkinter OSM tile widget).
- The RGBA coverage image is projected onto the tile canvas every 300 ms
  using `decimal_to_osm()` coordinate conversion (Mercator-correct).
- Overlay is skipped when: zoom ≥ 14 (too detailed), tab is not visible,
  or the viewport has not changed (state-tuple comparison).
- Tower markers are added in batches of 60 per UI tick (`root.after(1, ...)`)
  so the interface stays responsive even with thousands of markers.
- Minimum zoom = 9 to prevent excessive tile downloads.
- Markers are tiny PIL dot icons (11 px circles, no text label) — similar to
  the opencellid.org style. Clicking a marker shows `radio | radius` in a label.

### Tab 2 — Heatmap

The `create_heatmap_figure` matplotlib figure embedded via
`FigureCanvasTkAgg`. Two panels: coverage intensity and category map.

### Tab 3 — Gap Analysis

Gap overlay figure (top) + a `ttk.Treeview` table listing the top 10 gap clusters
with their coordinates, size in cells, and area in km² (bottom).

### Tab 4 — Simulation

The 3-panel simulation figure (top) + a summary bar with three `LabelFrame`
blocks showing before / after / improvement statistics side by side.

### Pipeline runner

- Runs in a **daemon thread** so the UI never freezes.
- `stdout` is redirected to a `queue.Queue`; a 100 ms `root.after` poll loop
  drains it into the dark-themed log Text widget.
- Matplotlib figures are built in the worker thread (`Agg` backend),
  then embedded in the main thread via `root.after`.

---

## 5. Libraries Used

| Library | Role |
|---------|------|
| `pandas` | Data loading, filtering, cleaning (chunked CSV read) |
| `numpy` | Grid operations, vectorised distance computation |
| `shapely` | Tower circle geometry (`Point.buffer`), gap `MultiPolygon` |
| `scipy` | Connected-component labelling (`ndimage.label`, `center_of_mass`) |
| `folium` | Interactive HTML map with `ImageOverlay` |
| `matplotlib` | Static PNG figures (heatmap, gap, simulation) |
| `contextily` | OSM basemap tiles under matplotlib axes |
| `tkintermapview` | Live tile-map widget inside Tkinter |
| `Pillow (PIL)` | RGBA image manipulation, dot marker icons |
| `tqdm` | Progress bar during rasterisation |

---

## 6. Key Algorithms Summary

| Algorithm | Where | Complexity |
|-----------|-------|-----------|
| Chunked CSV filter | `data_loader.py` | O(N) streaming |
| Path-loss radius | `signal_model.py` | O(N) vectorised |
| Bounding-box rasterisation | `rasterizer.py` | O(N · R²/cell²) |
| Connected-component labelling | `gap_analyzer.py` | O(H·W) |
| Vectorised region sizes (`bincount`) | `gap_analyzer.py` | O(H·W) |
| Batch centroid (`center_of_mass`) | `gap_analyzer.py` | O(H·W·K) |
| Log-scaled RGBA projection | `visualizer.py` | O(H·W) |
| Shapely `unary_union` (gap polygon) | `gap_analyzer.py` | O(B log B) |
| Mercator tile projection overlay | `app.py` | O(1) per frame |

---

## 7. What Still Could Be Improved

The project is functional and complete, but the following enhancements would
make it production-quality:

1. **Marker clustering** — At zoom-out levels, thousands of individual tower dots
   overlap. A clustering algorithm (e.g. `folium.plugins.MarkerCluster` or
   a custom quadtree) would group nearby towers into a single badge showing the count.

2. **Multi-city / configurable bounding box** — Currently hardcoded to Budapest.
   A config dialog or CLI argument could let the user specify any city name
   (geocoded via Nominatim) or a custom lat/lon bounding box.

3. **Real-time OpenCelliD API** — The app reads a static downloaded dump.
   The OpenCelliD API supports bbox queries; integrating it would always show
   up-to-date tower data without manual download steps.

4. **Faster rasterisation (Numba / GPU)** — The Python for-loop over towers,
   even with NumPy sub-grid operations, takes ~30–60 s for 15 000 towers on
   a 500 × 500 grid. A Numba JIT or CUDA kernel could reduce this to < 1 s.

5. **GeoJSON / Shapefile export** — The Shapely gap polygons could be exported
   as GeoJSON so urban planners could load them directly in QGIS.

6. **Signal strength heatmap** — Currently the grid counts towers per cell.
   Replacing this with a weighted `averageSignal` interpolation (e.g. IDW or
   kriging) would show actual signal quality rather than just presence/absence.

7. **Automatic data download** — The raw CSV requires a manual browser download
   and API token from OpenCelliD. A `requests`-based downloader with token
   management would make the app fully self-contained.

8. **Unit tests** — Each module has a `if __name__ == '__main__'` smoke test
   but no proper `pytest` test suite. Adding tests for edge cases (empty BBox,
   signal = 0, single tower, etc.) would improve reliability.

---

## 8. How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Place the downloaded OpenCelliD CSV:
#   data/raw/cell_towers.csv.gz

# Option A: Full GUI (recommended)
python app.py

# Option B: Headless pipeline (generates output files only)
python main.py
```

On the first run the rasterisation step takes ~1–2 minutes.
Subsequent runs use the cached `data/processed/coverage_grid.npy` and finish
in seconds.

---

*Report generated: 2026-05-09*
