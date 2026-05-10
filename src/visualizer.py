"""
Visualization layer for Project 12 - Mobile Tower Coverage Mapper.

Three figures + one interactive map:
  - create_heatmap_figure       -> coverage_overview.png style (categorical 5-tier)
  - create_gap_analysis_figure  -> gap-only red mask + numbered cluster pins
  - create_simulation_figure    -> 3-panel before/after/improvement with per-tower bar
  - create_folium_map           -> interactive HTML (kept; user said this is fine)

Design rationale (cf. industry tools like CellMapper/OpenSignal/FarrPoint):
  * Coverage data is HEAVILY skewed (city center 50-100+ towers/cell, suburbs 0-2);
    a continuous heatmap collapses to a single red blob. Categorical tiers
    map the meaningful 0-3 range to distinct colors.
  * The "delta" pattern: most pixels are context, change pops. We render the
    existing coverage as a grey basemap and only highlight the cells that
    actually changed in the simulation.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.figure
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import FancyBboxPatch, Circle
import folium

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GRID_RESOLUTION, BBOX, EARTH_RADIUS_M


# ===========================================================================
# Style + palette
# ===========================================================================

def _apply_dashboard_style() -> None:
    """Idempotent global rcParams update for a clean light dashboard look."""
    plt.rcParams.update({
        'font.family':       'DejaVu Sans',
        'font.size':         10,
        'figure.facecolor':  '#f7f8fa',
        'axes.facecolor':    '#ffffff',
        'axes.edgecolor':    '#dde2e8',
        'axes.linewidth':    0.8,
        'axes.labelcolor':   '#2c3e50',
        'axes.titlecolor':   '#1a242f',
        'axes.titlesize':    12,
        'axes.titleweight':  'bold',
        'axes.titlepad':     10,
        'text.color':        '#2c3e50',
        'xtick.color':       '#95a5a6',
        'ytick.color':       '#95a5a6',
        'xtick.labelsize':   9,
        'ytick.labelsize':   9,
        'axes.grid':         False,
        'legend.fontsize':   9,
        'legend.frameon':    True,
        'legend.facecolor':  'white',
        'legend.edgecolor':  '#dde2e8',
    })


# Radio types - kept stable across all figures and the Folium map
RADIO_COLORS = {
    'GSM':  '#3388ff',
    'UMTS': '#ff7800',
    'LTE':  '#00aa00',
    'NR':   '#aa00aa',
}

# Coverage tiers - the core categorical encoding.
# Bin edges are right-open: [0, 1) = Gap, [1, 2) = Marginal, [2, 4) = Adequate, ...
COVERAGE_TIER_BOUNDS = [0, 1, 2, 4, 10, 1_000_000]
COVERAGE_TIER_NAMES  = ['Gap', 'Marginal', 'Adequate', 'Strong', 'Saturated']
COVERAGE_TIER_COLORS = ['#d73027', '#fdae61', '#fee08b', '#a6d96a', '#1a9850']
COVERAGE_TIER_DESC   = ['no service', '1 tower',
                        '2-3 towers', '4-9 towers', '10+ towers']

# Diff / change palette (used only on simulation figure)
GAP_COLOR           = '#d73027'   # red - uncovered
GAP_FIXED_COLOR     = '#10b981'   # emerald green - was gap, now covered
REDUNDANCY_COLOR    = '#06b6d4'   # cyan - was covered, now more covered
PIN_COLOR           = '#dc2626'   # bright red drop pin
CLUSTER_PIN_COLOR   = '#1d4ed8'   # blue pin for gap-cluster centroids

# KPI accent colors
KPI_ACCENT  = '#2980b9'
KPI_GOOD    = '#27ae60'
KPI_BAD     = '#c0392b'

BASEMAP_ALPHA_GRAY  = 0.85
BASEMAP_ALPHA_COLOR = 0.55


# ===========================================================================
# Helpers
# ===========================================================================

def _geographic_aspect(bbox: dict) -> float:
    """Aspect ratio for matplotlib imshow so 1 km lat = 1 km lon visually."""
    center_lat = 0.5 * (bbox['lat_min'] + bbox['lat_max'])
    return 1.0 / np.cos(np.radians(center_lat))


def _try_add_basemap(ax, bbox: dict, gray: bool = False,
                     alpha: float | None = None) -> None:
    """
    Add a CartoDB Positron (labelled, light) basemap via contextily.
    `gray=True` keeps backward compatibility but visually we now always use
    Positron-with-labels - streets and the Danube show through the categorical
    overlay and give the maps actual context.
    Falls back silently if contextily/network not available.
    """
    if alpha is None:
        alpha = BASEMAP_ALPHA_GRAY if gray else BASEMAP_ALPHA_COLOR
    try:
        import contextily as ctx
        ax.set_xlim(bbox['lon_min'], bbox['lon_max'])
        ax.set_ylim(bbox['lat_min'], bbox['lat_max'])
        # Positron (labelled): clean light tiles with streets/labels - lets
        # the categorical overlay sit on top while keeping geographic context.
        provider = ctx.providers.CartoDB.Positron
        ctx.add_basemap(ax, crs='EPSG:4326', source=provider,
                        zorder=0, alpha=alpha)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cartographic furniture
# ---------------------------------------------------------------------------

def _add_scale_bar(ax, bbox: dict, length_km: float = 5.0,
                   y_frac: float = 0.04, x_frac: float = 0.04) -> None:
    """Draw a small distance scale bar in the lower-left of a map axis."""
    center_lat = 0.5 * (bbox['lat_min'] + bbox['lat_max'])
    deg_per_km_lon = 1.0 / (111.32 * np.cos(np.radians(center_lat)))
    length_deg = length_km * deg_per_km_lon

    lon_min, lon_max = bbox['lon_min'], bbox['lon_max']
    lat_min, lat_max = bbox['lat_min'], bbox['lat_max']
    x0 = lon_min + (lon_max - lon_min) * x_frac
    y0 = lat_min + (lat_max - lat_min) * y_frac

    bar_h = (lat_max - lat_min) * 0.005
    ax.add_patch(mpatches.Rectangle(
        (x0, y0), length_deg, bar_h,
        facecolor='#1f2937', edgecolor='white',
        linewidth=0.6, zorder=10,
    ))
    ax.text(x0 + length_deg / 2, y0 + bar_h * 4.0,
            f'{length_km:.0f} km', ha='center', va='bottom',
            fontsize=8.5, color='#1f2937', fontweight='bold', zorder=10,
            bbox=dict(facecolor='white', alpha=0.85,
                       edgecolor='none', pad=1.2))


def _add_north_arrow(ax, bbox: dict, x_frac: float = 0.95,
                     y_frac: float = 0.92) -> None:
    """Draw a small north arrow in the upper-right of a map axis."""
    lon_min, lon_max = bbox['lon_min'], bbox['lon_max']
    lat_min, lat_max = bbox['lat_min'], bbox['lat_max']
    x = lon_min + (lon_max - lon_min) * x_frac
    y = lat_min + (lat_max - lat_min) * y_frac
    arrow_len = (lat_max - lat_min) * 0.05
    ax.annotate(
        '', xy=(x, y + arrow_len), xytext=(x, y - arrow_len),
        arrowprops=dict(facecolor='#1f2937', edgecolor='white',
                         width=4, headwidth=12, headlength=10),
        zorder=10,
    )
    ax.text(x, y + arrow_len * 1.55, 'N', ha='center', va='bottom',
            fontsize=10, fontweight='bold', color='#1f2937', zorder=10,
            bbox=dict(facecolor='white', alpha=0.85,
                       edgecolor='none', pad=1.2))


def _add_tier_legend_strip(ax, bbox: dict) -> None:
    """
    Compact horizontal tier legend pinned to the bottom-centre of a map axis.
    Five swatches in a row + names + descriptions.
    """
    lon_min, lon_max = bbox['lon_min'], bbox['lon_max']
    lat_min, lat_max = bbox['lat_min'], bbox['lat_max']

    handles = [
        mpatches.Patch(facecolor=COVERAGE_TIER_COLORS[i],
                       edgecolor='white', linewidth=0.6,
                       label=f'{COVERAGE_TIER_NAMES[i]}\n{COVERAGE_TIER_DESC[i]}')
        for i in range(5)
    ]
    leg = ax.legend(
        handles=handles,
        loc='lower center',
        bbox_to_anchor=(0.5, 0.0),
        ncol=5, fontsize=8.5,
        frameon=True, framealpha=0.92,
        handleheight=1.6, handlelength=1.6,
        columnspacing=1.4, borderpad=0.7,
    )
    leg.get_frame().set_edgecolor('#dde2e8')
    leg.get_frame().set_linewidth(0.8)


def _style_map_axes(ax, bbox: dict, show_labels: bool = True) -> None:
    """Common map-axes styling with correct geographic aspect."""
    ax.set_xlim(bbox['lon_min'], bbox['lon_max'])
    ax.set_ylim(bbox['lat_min'], bbox['lat_max'])
    ax.set_aspect(_geographic_aspect(bbox))
    if show_labels:
        ax.set_xlabel('Longitude (°)', fontsize=9)
        ax.set_ylabel('Latitude (°)', fontsize=9)
    else:
        ax.set_xticks([])
        ax.set_yticks([])
    ax.tick_params(labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor('#dde2e8')
        spine.set_linewidth(0.8)


def _coverage_categorical_rgba(coverage: np.ndarray,
                               alpha: float = 0.70) -> np.ndarray:
    """5-tier categorical RGBA image (Gap/Marginal/Adequate/Strong/Saturated)."""
    cmap = ListedColormap(COVERAGE_TIER_COLORS)
    norm = BoundaryNorm(COVERAGE_TIER_BOUNDS, cmap.N)
    rgba = cmap(norm(coverage)).astype(float)
    rgba[..., 3] = alpha
    return rgba


def _to_uint8_rgba(rgba_float: np.ndarray) -> np.ndarray:
    """
    Convert a 0-1 float RGBA array to uint8 0-255 - required by folium /
    branca.image_to_url, which otherwise renormalises each channel to its
    min/max and corrupts solid-colour masks (red mask -> white!).
    """
    return np.clip(rgba_float * 255, 0, 255).astype(np.uint8)


def _mask_rgba_for_folium(mask: np.ndarray, color: str,
                          alpha: float = 0.55) -> np.ndarray:
    """
    uint8 RGBA image where mask=True is coloured, transparent elsewhere -
    flipped north-up so it can be passed straight to folium.ImageOverlay.
    """
    rgba = mcolors.to_rgba(color, alpha=alpha)
    overlay = np.zeros((*mask.shape, 4), dtype=np.uint8)
    overlay[mask] = [int(rgba[0] * 255), int(rgba[1] * 255),
                     int(rgba[2] * 255), int(rgba[3] * 255)]
    return np.flipud(overlay)


def _coverage_continuous_rgba(coverage: np.ndarray, cmap_name: str = 'YlOrRd',
                              max_alpha: float = 0.75) -> np.ndarray:
    """
    Log-scaled continuous heatmap RGBA - the variant used in the interactive
    Folium map (smooth gradient instead of discrete tiers).
    """
    vmax = max(int(coverage.max()), 2)
    cmap = plt.cm.get_cmap(cmap_name)
    norm = mcolors.LogNorm(vmin=1, vmax=vmax)
    colored = cmap(norm(coverage.clip(min=1))).astype(float)
    log_ratio = np.where(
        coverage > 0,
        np.log1p(coverage.astype(float)) / np.log1p(vmax),
        0.0,
    )
    colored[..., 3] = np.clip(log_ratio * max_alpha, 0.0, max_alpha)
    return colored


def _mask_overlay(mask: np.ndarray, color: str, alpha: float) -> np.ndarray:
    """RGBA overlay where mask=True is colored, rest is fully transparent."""
    overlay = np.zeros((*mask.shape, 4), dtype=float)
    overlay[mask] = mcolors.to_rgba(color, alpha=alpha)
    return overlay


def _draw_tower_pin(ax, lon: float, lat: float, label: str | None = None,
                    radius_deg: float | None = None,
                    color: str = PIN_COLOR, size: int = 22,
                    show_radius: bool = False) -> None:
    """
    Drop-pin marker (red disc with white outline + numeric label).
    Optional dashed coverage-radius outline.
    """
    if show_radius and radius_deg is not None:
        circle = Circle((lon, lat), radius_deg, fill=False,
                        edgecolor=color, linewidth=1.6,
                        linestyle=(0, (4, 3)), alpha=0.85, zorder=5)
        ax.add_patch(circle)

    # White soft halo - lifts the pin off the basemap
    ax.plot(lon, lat, marker='o', markersize=size + 6,
            color='white', alpha=0.85,
            markeredgecolor='none', zorder=6)
    # Pin body
    ax.plot(lon, lat, marker='o', markersize=size,
            color=color, markeredgecolor='white',
            markeredgewidth=2.0, zorder=7)
    # Numeric label inside
    if label is not None:
        ax.text(lon, lat, str(label), ha='center', va='center',
                fontsize=int(size * 0.5), color='white',
                fontweight='bold', zorder=8)


def _draw_kpi_card(ax, x: float, y: float, w: float, h: float,
                   label: str, value: str,
                   value_color: str = KPI_ACCENT,
                   sub: str | None = None,
                   sub_color: str = '#7f8c8d') -> None:
    """Card-style KPI: label, big value, optional sub-label."""
    shadow = FancyBboxPatch(
        (x + 0.005, y - 0.012), w, h,
        boxstyle='round,pad=0.005,rounding_size=0.012',
        linewidth=0, facecolor='#000000', alpha=0.06,
        transform=ax.transAxes, zorder=1,
    )
    ax.add_patch(shadow)
    card = FancyBboxPatch(
        (x, y), w, h,
        boxstyle='round,pad=0.005,rounding_size=0.012',
        linewidth=1.0, edgecolor='#dde2e8', facecolor='white',
        transform=ax.transAxes, zorder=2,
    )
    ax.add_patch(card)
    ax.text(x + w / 2, y + h * 0.74, label,
            transform=ax.transAxes, ha='center', va='center',
            fontsize=9, color='#7f8c8d', fontweight='bold', zorder=3)
    ax.text(x + w / 2, y + h * 0.42, value,
            transform=ax.transAxes, ha='center', va='center',
            fontsize=20, color=value_color, fontweight='bold', zorder=3)
    if sub is not None:
        ax.text(x + w / 2, y + h * 0.16, sub,
                transform=ax.transAxes, ha='center', va='center',
                fontsize=8.5, color=sub_color, zorder=3)


def _kpi_strip(ax, cards: list[tuple]) -> None:
    """Render up to 4 KPI cards across the strip axis (transAxes-based)."""
    ax.axis('off')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    n = len(cards)
    card_w = 0.225
    card_h = 0.86
    card_y = 0.07
    pad = (1.0 - n * card_w) / (n + 1)
    for i, card in enumerate(cards):
        label, value, color, sub = card
        x = pad + i * (card_w + pad)
        _draw_kpi_card(ax, x, card_y, card_w, card_h,
                       label, value, value_color=color, sub=sub)


def _radio_summary(towers_df: pd.DataFrame) -> str:
    counts = towers_df['radio'].value_counts()
    return ' · '.join(f"{r} {c:,}" for r, c in counts.items())


def _tier_areas_km2(coverage: np.ndarray, cell_area_km2: float) -> list[float]:
    """Area (km²) in each of the 5 coverage tiers."""
    out = []
    for i in range(5):
        lo, hi = COVERAGE_TIER_BOUNDS[i], COVERAGE_TIER_BOUNDS[i + 1]
        n_cells = int(((coverage >= lo) & (coverage < hi)).sum())
        out.append(n_cells * cell_area_km2)
    return out


# ===========================================================================
# 1. Folium interactive map (kept - user said this output is fine)
# ===========================================================================

def create_folium_map(towers_df: pd.DataFrame, coverage: np.ndarray,
                      grid_lat: np.ndarray, grid_lon: np.ndarray,
                      stats: dict) -> folium.Map:
    """Build an interactive Folium map with continuous log-scaled coverage,
    gap markers and tower markers (the version users liked)."""
    m = folium.Map(location=[47.5, 19.1], zoom_start=11, tiles='OpenStreetMap')

    rgba = _coverage_continuous_rgba(coverage, cmap_name='YlOrRd', max_alpha=0.75)
    rgba_img = _to_uint8_rgba(np.flipud(rgba))
    bounds = [[float(grid_lat[0, 0]),  float(grid_lon[0, 0])],
              [float(grid_lat[-1, 0]), float(grid_lon[0, -1])]]
    folium.raster_layers.ImageOverlay(
        image=rgba_img, bounds=bounds, opacity=1.0,
        name='Coverage heatmap', interactive=False, cross_origin=False,
        mercator_project=True,
    ).add_to(m)

    gap_group = folium.FeatureGroup(name='Gap areas', show=False)
    gap_mask = stats['gap_mask']
    sub_mask = gap_mask[::5, ::5]
    gap_lats = grid_lat[::5, ::5][sub_mask]
    gap_lons = grid_lon[::5, ::5][sub_mask]
    for lat, lon in zip(gap_lats, gap_lons):
        folium.CircleMarker(
            location=[lat, lon], radius=3, color=GAP_COLOR, fill=True,
            fill_opacity=0.5, weight=0,
        ).add_to(gap_group)
    gap_group.add_to(m)

    tower_group = folium.FeatureGroup(name='Towers', show=True)
    sample_df = towers_df if len(towers_df) <= 5000 else towers_df.sample(2000, random_state=42)
    for _, row in sample_df.iterrows():
        color = RADIO_COLORS.get(row['radio'], '#888888')
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=4, color=color, fill=True, fill_opacity=0.75,
            popup=f"<b>{row['radio']}</b><br>radius: {row.get('radius', 300):.0f} m",
        ).add_to(tower_group)
    tower_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    coverage_pct = (1 - stats['gap_fraction']) * 100
    info_html = f"""
    <div style="position:fixed; top:12px; left:60px; z-index:1000;
                background:white; padding:12px 14px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.25);
                font-family:'Segoe UI',sans-serif; font-size:13px; line-height:1.5;">
      <div style="font-size:14px; font-weight:600; margin-bottom:6px;
                  border-bottom:1px solid #ddd; padding-bottom:4px;">
        Budapest Mobile Network
      </div>
      <div><b>Towers:</b> {len(towers_df):,}</div>
      <div><b>Coverage:</b> {coverage_pct:.1f}%</div>
      <div><b>Gap area:</b> {stats['gap_area_km2']:.1f} km&sup2;</div>
      <div><b>Avg towers/cell:</b> {stats['mean_coverage']:.2f}</div>
    </div>
    """

    radio_legend = ''.join(
        f'<div style="display:flex; align-items:center; margin:2px 0;">'
        f'<span style="display:inline-block; width:12px; height:12px; '
        f'background:{c}; border-radius:50%; margin-right:6px;"></span>{r}</div>'
        for r, c in RADIO_COLORS.items()
    )
    legend_html = f"""
    <div style="position:fixed; top:12px; right:60px; z-index:1000;
                background:white; padding:10px 12px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.25);
                font-family:'Segoe UI',sans-serif; font-size:12px;">
      <div style="font-weight:600; margin-bottom:4px;">Radio type</div>
      {radio_legend}
    </div>
    """

    m.get_root().html.add_child(folium.Element(info_html))
    m.get_root().html.add_child(folium.Element(legend_html))
    return m


# ---------------------------------------------------------------------------
# Folium helpers used by the gap & simulation interactive maps
# ---------------------------------------------------------------------------

def _folium_image_layer(rgba_north_up: np.ndarray, grid_lat: np.ndarray,
                        grid_lon: np.ndarray, name: str,
                        show: bool = True,
                        mercator_project: bool = False
                        ) -> folium.raster_layers.ImageOverlay:
    """
    mercator_project=False is critical for solid-colour mask overlays:
    folium's mercator_transform copies the array to float64, then
    branca.write_png renormalises each channel per-max, which collapses a
    uniformly red mask to pure white. At Budapest's bbox the projection
    distortion from skipping the reprojection is < 1 %.
    """
    bounds = [[float(grid_lat[0, 0]),  float(grid_lon[0, 0])],
              [float(grid_lat[-1, 0]), float(grid_lon[0, -1])]]
    return folium.raster_layers.ImageOverlay(
        image=rgba_north_up, bounds=bounds, opacity=1.0,
        name=name, interactive=False, cross_origin=False,
        mercator_project=mercator_project, show=show,
    )


def _numbered_pin_marker(lat: float, lon: float, label: str | int,
                         color: str, popup_html: str) -> folium.Marker:
    """Map-pin style numbered marker: coloured disc with white label inside."""
    icon_html = (
        f'<div style="width:30px; height:30px; border-radius:50%;'
        f' background:{color}; border:2px solid white;'
        f' box-shadow:0 1px 4px rgba(0,0,0,0.4); color:white;'
        f' font: bold 13px/26px \'Segoe UI\', sans-serif;'
        f' text-align:center;">{label}</div>'
    )
    return folium.Marker(
        location=[lat, lon],
        icon=folium.DivIcon(html=icon_html, icon_size=(30, 30),
                             icon_anchor=(15, 15)),
        popup=folium.Popup(popup_html, max_width=300),
    )


# ===========================================================================
# 1b. Gap analysis interactive map (gap_analysis.html)
# ===========================================================================

def create_gap_analysis_map(coverage: np.ndarray, stats: dict, clusters: list,
                            grid_lat: np.ndarray, grid_lon: np.ndarray,
                            towers_df: pd.DataFrame) -> folium.Map:
    """Interactive gap-analysis map: red gap overlay + numbered cluster pins."""
    # Light Carto Positron tiles let the red gap overlay pop (OSM Mapnik
    # is too colourful and the gap layer disappears into it).
    m = folium.Map(
        location=[47.5, 19.1], zoom_start=11,
        tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        attr='&copy; OpenStreetMap, &copy; CartoDB',
    )

    cell_area = stats['cell_area_km2']

    # Gap raster overlay (red where gap_mask is True, transparent elsewhere)
    gap_rgba = _mask_rgba_for_folium(stats['gap_mask'], GAP_COLOR, alpha=0.75)
    _folium_image_layer(gap_rgba, grid_lat, grid_lon,
                        name='Gap (no service)', show=True).add_to(m)

    # Coverage tiers as alternative layer (default off)
    tier_rgba = _to_uint8_rgba(np.flipud(_coverage_categorical_rgba(coverage, alpha=0.55)))
    _folium_image_layer(tier_rgba, grid_lat, grid_lon,
                        name='Coverage tiers (5 levels)',
                        show=False).add_to(m)

    # Continuous heatmap as third alternative
    cont_rgba = _to_uint8_rgba(np.flipud(_coverage_continuous_rgba(coverage,
                                                                    cmap_name='YlOrRd',
                                                                    max_alpha=0.75)))
    _folium_image_layer(cont_rgba, grid_lat, grid_lon,
                        name='Coverage heatmap (log)',
                        show=False).add_to(m)

    # Top-10 cluster pins (top-5 emphasised in blue, rest in grey)
    cluster_group = folium.FeatureGroup(name='Top-10 gap clusters', show=True)
    for i, c in enumerate(clusters[:10], start=1):
        size_km2 = c['size_cells'] * cell_area
        color = CLUSTER_PIN_COLOR if i <= 5 else '#94a3b8'
        popup_html = (
            f'<div style="font: 13px/1.4 \'Segoe UI\',sans-serif;">'
            f'<div style="font-weight:600; font-size:14px; color:{color};'
            f' border-bottom:1px solid #ddd; padding-bottom:4px;'
            f' margin-bottom:6px;">Gap cluster #{i}</div>'
            f'<b>Area:</b> {size_km2:.2f} km²<br>'
            f'<b>Cells:</b> {c["size_cells"]:,}<br>'
            f'<b>Centroid:</b> {c["lat"]:.4f}, {c["lon"]:.4f}'
            f'</div>'
        )
        _numbered_pin_marker(c['lat'], c['lon'], i, color,
                              popup_html).add_to(cluster_group)
    cluster_group.add_to(m)

    # Existing towers - sampled, default off (can clutter quickly)
    tower_group = folium.FeatureGroup(name='Existing towers (sampled)',
                                       show=False)
    sample_df = towers_df if len(towers_df) <= 5000 else towers_df.sample(2000, random_state=42)
    for _, row in sample_df.iterrows():
        c = RADIO_COLORS.get(row['radio'], '#888888')
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=4, color=c, fill=True, fill_opacity=0.7,
            popup=f"<b>{row['radio']}</b><br>radius: {row.get('radius', 300):.0f} m",
        ).add_to(tower_group)
    tower_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Floating KPI panel
    largest = (clusters[0]['size_cells'] * cell_area) if clusters else 0.0
    info_html = f"""
    <div style="position:fixed; top:12px; left:60px; z-index:1000;
                background:white; padding:12px 14px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.25);
                font-family:'Segoe UI',sans-serif; font-size:13px; line-height:1.5;">
      <div style="font-size:14px; font-weight:600; margin-bottom:6px;
                  border-bottom:1px solid #ddd; padding-bottom:4px;">
        Gap Analysis – Budapest
      </div>
      <div><b>Total gap:</b> {stats['gap_area_km2']:.1f} km²
        ({stats['gap_fraction']*100:.1f}%)</div>
      <div><b>Gap cells:</b> {stats['gap_cells']:,}</div>
      <div><b>Clusters found:</b> {len(clusters)}</div>
      <div><b>Largest cluster:</b> {largest:.1f} km²</div>
      <div style="font-size:11px; color:#7f8c8d; margin-top:6px;
                  border-top:1px solid #eee; padding-top:4px;">
        Click a pin for cluster details · toggle layers in the panel →
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))
    return m


# ===========================================================================
# 1c. Simulation interactive map (simulation_report.html)
# ===========================================================================

def create_simulation_map(sim_results: dict, grid_lat: np.ndarray,
                          grid_lon: np.ndarray) -> folium.Map:
    """
    Interactive network expansion map.

    Toggleable raster layers:
      - Coverage tiers AFTER (default on)
      - Coverage tiers BEFORE
      - Gap mask BEFORE (red)
      - Gap mask AFTER (red)
      - Improvement: gap → covered (green, default on)
      - Added redundancy (cyan, default on)
    Always visible:
      - Numbered new-tower pins with popups (radius, contribution km²)
      - Folium Circle around each new tower (= coverage radius)
    """
    before_grid  = sim_results['original_grid']
    after_grid   = sim_results['new_coverage_grid']
    new_towers   = sim_results['new_towers']
    before_stats = sim_results['before']
    after_stats  = sim_results['after']
    per_tower    = sim_results.get('per_tower_contribution', [])

    # Light Carto Positron tiles - same reasoning as the gap-analysis map:
    # the deltas (red/green/cyan) need to pop, which requires a calm basemap.
    m = folium.Map(
        location=[47.5, 19.1], zoom_start=11,
        tiles='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
        attr='&copy; OpenStreetMap, &copy; CartoDB',
    )

    # ----- Raster layers ----------------------------------------------------
    after_tiers  = _to_uint8_rgba(np.flipud(_coverage_categorical_rgba(after_grid, alpha=0.55)))
    before_tiers = _to_uint8_rgba(np.flipud(_coverage_categorical_rgba(before_grid, alpha=0.55)))
    _folium_image_layer(after_tiers,  grid_lat, grid_lon,
                        name='Coverage tiers AFTER',  show=True).add_to(m)
    _folium_image_layer(before_tiers, grid_lat, grid_lon,
                        name='Coverage tiers BEFORE', show=False).add_to(m)

    gap_before_rgba = _mask_rgba_for_folium(before_stats['gap_mask'],
                                             GAP_COLOR, alpha=0.70)
    gap_after_rgba  = _mask_rgba_for_folium(after_stats['gap_mask'],
                                             GAP_COLOR, alpha=0.70)
    _folium_image_layer(gap_before_rgba, grid_lat, grid_lon,
                        name='Gap mask BEFORE (red)', show=False).add_to(m)
    _folium_image_layer(gap_after_rgba,  grid_lat, grid_lon,
                        name='Gap mask AFTER (red)',  show=False).add_to(m)

    fixed_mask = (before_grid == 0) & (after_grid >= 1)
    redundancy_mask = (after_grid > before_grid) & (before_grid > 0)
    if redundancy_mask.any():
        red_rgba = _mask_rgba_for_folium(redundancy_mask,
                                          REDUNDANCY_COLOR, alpha=0.55)
        _folium_image_layer(red_rgba, grid_lat, grid_lon,
                            name='Added redundancy (cyan)',
                            show=True).add_to(m)
    if fixed_mask.any():
        fix_rgba = _mask_rgba_for_folium(fixed_mask,
                                          GAP_FIXED_COLOR, alpha=0.85)
        _folium_image_layer(fix_rgba, grid_lat, grid_lon,
                            name='Improvement: gap → covered (green)',
                            show=True).add_to(m)

    # ----- New tower pins + coverage circles --------------------------------
    pin_group = folium.FeatureGroup(name='New towers + coverage circles',
                                     show=True)
    for i, t in enumerate(new_towers, start=1):
        contrib = per_tower[i - 1] if per_tower else None
        contrib_line = (
            f'<b>Standalone gap fix:</b> {contrib:.2f} km²<br>'
            if contrib is not None else ''
        )
        popup_html = (
            f'<div style="font: 13px/1.4 \'Segoe UI\',sans-serif;">'
            f'<div style="font-weight:600; font-size:14px; color:{PIN_COLOR};'
            f' border-bottom:1px solid #ddd; padding-bottom:4px;'
            f' margin-bottom:6px;">New tower #{i}</div>'
            f'<b>Type:</b> {t.get("radio", "LTE")}<br>'
            f'<b>Coverage radius:</b> {t["radius"]:.0f} m<br>'
            f'<b>Location:</b> {t["lat"]:.4f}, {t["lon"]:.4f}<br>'
            f'{contrib_line}'
            f'</div>'
        )
        # Coverage circle
        folium.Circle(
            location=[t['lat'], t['lon']],
            radius=t['radius'], color=PIN_COLOR, weight=2,
            dash_array='5,4', fill=False,
        ).add_to(pin_group)
        # Numbered pin
        _numbered_pin_marker(t['lat'], t['lon'], i, PIN_COLOR,
                              popup_html).add_to(pin_group)
    pin_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Floating KPI panel
    cov_before = (1 - before_stats['gap_fraction']) * 100
    cov_after  = (1 - after_stats['gap_fraction']) * 100
    delta_km2  = sim_results['gap_reduction_km2']
    delta_pct  = sim_results['gap_reduction_pct']
    info_html = f"""
    <div style="position:fixed; top:12px; left:60px; z-index:1000;
                background:white; padding:12px 14px; border-radius:8px;
                box-shadow:0 2px 8px rgba(0,0,0,0.25);
                font-family:'Segoe UI',sans-serif; font-size:13px; line-height:1.5;">
      <div style="font-size:14px; font-weight:600; margin-bottom:6px;
                  border-bottom:1px solid #ddd; padding-bottom:4px;">
        Network Expansion Plan
      </div>
      <div><b>Coverage:</b> {cov_before:.1f}% → <span style="color:#16a34a;">{cov_after:.1f}%</span></div>
      <div><b>Gap before:</b> {before_stats['gap_area_km2']:.1f} km²</div>
      <div><b>Gap after:</b> {after_stats['gap_area_km2']:.1f} km²</div>
      <div><b>Reduction:</b> <span style="color:#16a34a; font-weight:600;">
        -{delta_km2:.1f} km² ({delta_pct:.1f}%)</span></div>
      <div><b>New towers:</b> {len(new_towers)} · LTE · {new_towers[0]['radius']:.0f} m radius</div>
      <div style="font-size:11px; color:#7f8c8d; margin-top:6px;
                  border-top:1px solid #eee; padding-top:4px;">
        Click a numbered pin for tower details · toggle layers in the panel →<br>
        Try toggling <b>BEFORE</b> vs <b>AFTER</b> tier layers to compare.
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))
    return m


# ===========================================================================
# 2. Coverage Overview (heatmap.png)
# ===========================================================================

def create_heatmap_figure(coverage: np.ndarray, bbox: dict, stats: dict,
                          towers_df: pd.DataFrame) -> matplotlib.figure.Figure:
    """
    Coverage Overview - hero map design.

    Layout
        [ HEADER (slim) ]
        [ BIG CATEGORICAL MAP (full width)           ]
        [ KPI strip                                  ]
    """
    _apply_dashboard_style()

    fig = plt.figure(figsize=(15, 13), layout='constrained',
                     facecolor=plt.rcParams['figure.facecolor'])
    gs = fig.add_gridspec(
        nrows=3, ncols=1,
        height_ratios=[0.75, 10.0, 1.4],
        hspace=0.03,
    )

    coverage_pct = (1 - stats['gap_fraction']) * 100

    # ----- Header -----------------------------------------------------------
    header = fig.add_subplot(gs[0, 0])
    header.axis('off')
    header.text(0.0, 0.78, 'Mobile Tower Coverage – Budapest',
                transform=header.transAxes, ha='left', va='center',
                fontsize=24, fontweight='bold', color='#1a242f')
    header.text(0.0, 0.28,
                f'OpenCelliD dataset · {len(towers_df):,} towers · '
                f'{GRID_RESOLUTION}×{GRID_RESOLUTION} grid · '
                f'{_radio_summary(towers_df)}',
                transform=header.transAxes, ha='left', va='center',
                fontsize=11, color='#7f8c8d')
    header.text(1.0, 0.55, f'{coverage_pct:.1f}%',
                transform=header.transAxes, ha='right', va='center',
                fontsize=34, fontweight='bold', color=KPI_ACCENT)

    # ----- Hero map ---------------------------------------------------------
    ax = fig.add_subplot(gs[1, 0])
    extent = [bbox['lon_min'], bbox['lon_max'], bbox['lat_min'], bbox['lat_max']]

    _try_add_basemap(ax, bbox, alpha=0.95)
    rgba = _coverage_categorical_rgba(coverage, alpha=0.55)
    ax.imshow(rgba, origin='lower', extent=extent,
              aspect='auto', interpolation='nearest', zorder=2)

    _style_map_axes(ax, bbox, show_labels=False)
    ax.set_title('Coverage tiers · streets and landmarks visible through the overlay',
                 loc='left', fontsize=12)

    _add_scale_bar(ax, bbox, length_km=5.0)
    _add_north_arrow(ax, bbox)
    _add_tier_legend_strip(ax, bbox)

    # ----- KPI strip --------------------------------------------------------
    ax_kpi = fig.add_subplot(gs[2, 0])
    tier_km2 = _tier_areas_km2(coverage, stats['cell_area_km2'])
    saturated_km2 = tier_km2[4]
    cards = [
        ('TOTAL TOWERS', f'{len(towers_df):,}', KPI_ACCENT,
            _radio_summary(towers_df)),
        ('GAP AREA',     f'{stats["gap_area_km2"]:.0f} km²', KPI_BAD,
            f'{stats["gap_fraction"]*100:.1f}% of '
            f'{stats["total_area_km2"]:.0f} km²'),
        ('WELL-SERVED',  f'{stats["overlap_area_km2"]:.0f} km²', KPI_GOOD,
            f'≥2 towers · {stats["overlap_fraction"]*100:.1f}%'),
        ('SATURATED CORE', f'{saturated_km2:.0f} km²', KPI_ACCENT,
            f'10+ towers/cell · peak {stats["max_coverage"]}'),
    ]
    _kpi_strip(ax_kpi, cards)
    return fig


# ===========================================================================
# 3. Gap analysis (gap_analysis.png)
# ===========================================================================

def create_gap_analysis_figure(coverage: np.ndarray, stats: dict,
                               clusters: list, grid_lat: np.ndarray,
                               grid_lon: np.ndarray,
                               bbox: dict) -> matplotlib.figure.Figure:
    """
    Gap analysis - hero map design.

    Layout
        [ HEADER ]
        [ BIG GAP MAP - red overlay + numbered pins with size annotations ]
        [ KPI strip ]
    """
    _apply_dashboard_style()

    fig = plt.figure(figsize=(15, 13), layout='constrained',
                     facecolor=plt.rcParams['figure.facecolor'])
    gs = fig.add_gridspec(
        nrows=3, ncols=1,
        height_ratios=[0.75, 10.0, 1.4],
        hspace=0.03,
    )

    gap_pct = stats['gap_fraction'] * 100
    cell_area = stats['cell_area_km2']

    # ----- Header -----------------------------------------------------------
    header = fig.add_subplot(gs[0, 0])
    header.axis('off')
    header.text(0.0, 0.78, 'Gap Analysis – Budapest',
                transform=header.transAxes, ha='left', va='center',
                fontsize=24, fontweight='bold', color='#1a242f')
    header.text(0.0, 0.28,
                f'Uncovered cells highlighted in red · '
                f'{len(clusters)} largest clusters identified · '
                f'top 5 marked with numbered pins and size annotations',
                transform=header.transAxes, ha='left', va='center',
                fontsize=11, color='#7f8c8d')
    header.text(1.0, 0.55, f'{stats["gap_area_km2"]:.0f} km²',
                transform=header.transAxes, ha='right', va='center',
                fontsize=34, fontweight='bold', color=KPI_BAD)

    # ----- Hero map ---------------------------------------------------------
    ax = fig.add_subplot(gs[1, 0])
    extent = [bbox['lon_min'], bbox['lon_max'],
              bbox['lat_min'], bbox['lat_max']]

    _try_add_basemap(ax, bbox, alpha=0.95)
    gap_overlay = _mask_overlay(stats['gap_mask'], GAP_COLOR, alpha=0.55)
    ax.imshow(gap_overlay, origin='lower', extent=extent,
              aspect='auto', interpolation='nearest', zorder=2)

    # Pins + size annotations next to each (replaces the side ranking bar)
    lat_range = bbox['lat_max'] - bbox['lat_min']
    lon_range = bbox['lon_max'] - bbox['lon_min']
    lon_mid = 0.5 * (bbox['lon_min'] + bbox['lon_max'])
    lat_mid = 0.5 * (bbox['lat_min'] + bbox['lat_max'])
    for i, c in enumerate(clusters[:5], start=1):
        size_km2 = c['size_cells'] * cell_area
        _draw_tower_pin(ax, c['lon'], c['lat'], label=str(i),
                        color=CLUSTER_PIN_COLOR, size=24)
        # Position annotation away from the nearest map edge so it never clips
        right_side  = c['lon'] > lon_mid
        bottom_side = c['lat'] < lat_mid
        dx = -lon_range * 0.025 if right_side else lon_range * 0.025
        # Push annotation AWAY from the nearest top/bottom edge:
        # pin near bottom -> annotation above (dy > 0); pin near top -> below
        dy = lat_range * 0.018 * (1 if bottom_side else -1)
        ha = 'right' if right_side else 'left'
        ax.annotate(
            f'{size_km2:.1f} km²',
            xy=(c['lon'], c['lat']),
            xytext=(c['lon'] + dx, c['lat'] + dy),
            ha=ha, va='center',
            fontsize=10, fontweight='bold', color='#1f2937', zorder=11,
            bbox=dict(boxstyle='round,pad=0.3',
                       facecolor='white', edgecolor=CLUSTER_PIN_COLOR,
                       linewidth=1.3, alpha=0.95),
        )

    _style_map_axes(ax, bbox, show_labels=False)
    ax.set_title(f'Gap distribution · {gap_pct:.1f}% of area uncovered',
                 loc='left', fontsize=12)

    legend_handles = [
        mpatches.Patch(color=GAP_COLOR, alpha=0.55, label='Gap (no service)'),
        plt.Line2D([0], [0], marker='o', color='w',
                    markerfacecolor=CLUSTER_PIN_COLOR,
                    markeredgecolor='white', markeredgewidth=1.5,
                    markersize=11, label='Top-5 cluster centroid'),
    ]
    ax.legend(handles=legend_handles, loc='upper left',
              framealpha=0.95, fontsize=9.5)

    _add_scale_bar(ax, bbox, length_km=5.0)
    _add_north_arrow(ax, bbox)

    # ----- KPI strip --------------------------------------------------------
    ax_kpi = fig.add_subplot(gs[2, 0])
    largest = (clusters[0]['size_cells'] * cell_area) if clusters else 0.0
    largest_loc = (f"{clusters[0]['lat']:.3f}, {clusters[0]['lon']:.3f}"
                   if clusters else '—')
    cards = [
        ('TOTAL GAP',       f'{stats["gap_area_km2"]:.0f} km²', KPI_BAD,
            f'{gap_pct:.1f}% of {stats["total_area_km2"]:.0f} km²'),
        ('GAP CELLS',       f'{stats["gap_cells"]:,}', KPI_BAD,
            f'on {GRID_RESOLUTION}×{GRID_RESOLUTION} grid'),
        ('LARGEST CLUSTER', f'{largest:.1f} km²', KPI_BAD,
            f'centroid {largest_loc}'),
        ('CLUSTERS FOUND',  f'{len(clusters)}', KPI_ACCENT,
            'top 5 marked with pins'),
    ]
    _kpi_strip(ax_kpi, cards)
    return fig


# ===========================================================================
# 4. Network expansion (simulation_report.png)
# ===========================================================================

def create_simulation_figure(sim_results: dict, grid_lat: np.ndarray,
                             grid_lon: np.ndarray,
                             bbox: dict) -> matplotlib.figure.Figure:
    """
    Network Expansion Plan - 3 hero maps + slim per-tower bar + KPI strip.

    Layout
        [ HEADER ]
        [ GAPS BEFORE | GAPS AFTER + pins | IMPROVEMENT (delta map) ]
        [ Per-tower contribution bar (left)  |   KPI strip (right) ]
    """
    _apply_dashboard_style()

    before_grid  = sim_results['original_grid']
    after_grid   = sim_results['new_coverage_grid']
    new_towers   = sim_results['new_towers']
    before_stats = sim_results['before']
    after_stats  = sim_results['after']
    per_tower    = sim_results.get('per_tower_contribution', [])

    cov_before = (1 - before_stats['gap_fraction']) * 100
    cov_after  = (1 - after_stats['gap_fraction']) * 100
    delta_km2  = sim_results['gap_reduction_km2']
    delta_pct  = sim_results['gap_reduction_pct']

    fig = plt.figure(figsize=(22, 14), layout='constrained',
                     facecolor=plt.rcParams['figure.facecolor'])
    gs = fig.add_gridspec(
        nrows=3, ncols=3,
        height_ratios=[0.8, 9.0, 2.2],
        hspace=0.04, wspace=0.04,
    )

    # ----- Header -----------------------------------------------------------
    header = fig.add_subplot(gs[0, :])
    header.axis('off')
    header.text(0.0, 0.78, 'Network Expansion Plan – Budapest',
                transform=header.transAxes, ha='left', va='center',
                fontsize=24, fontweight='bold', color='#1a242f')
    header.text(0.0, 0.30,
                f'{len(new_towers)} hypothetical LTE towers · '
                f'{new_towers[0]["radius"]:.0f} m radius each · '
                f'Coverage {cov_before:.1f}% → {cov_after:.1f}% '
                f'({cov_after - cov_before:+.1f} pts)',
                transform=header.transAxes, ha='left', va='center',
                fontsize=11, color='#7f8c8d')
    delta_label = f'-{delta_km2:.1f} km²' if delta_km2 > 0 else f'{delta_km2:.1f} km²'
    header.text(1.0, 0.55, delta_label,
                transform=header.transAxes, ha='right', va='center',
                fontsize=30, fontweight='bold',
                color=KPI_GOOD if delta_km2 > 0 else KPI_BAD)

    extent = [bbox['lon_min'], bbox['lon_max'],
              bbox['lat_min'], bbox['lat_max']]

    # ----- Panel 1: GAPS BEFORE --------------------------------------------
    ax1 = fig.add_subplot(gs[1, 0])
    _try_add_basemap(ax1, bbox, alpha=0.95)
    o1 = _mask_overlay(before_stats['gap_mask'], GAP_COLOR, alpha=0.55)
    ax1.imshow(o1, origin='lower', extent=extent,
               aspect='auto', interpolation='nearest', zorder=2)
    _style_map_axes(ax1, bbox, show_labels=False)
    ax1.set_title(f'BEFORE  ·  {before_stats["gap_area_km2"]:.0f} km² in gaps',
                  loc='left', fontsize=12)
    ax1.legend(
        handles=[mpatches.Patch(color=GAP_COLOR, alpha=0.55,
                                 label='Gap (no service)')],
        loc='upper left', framealpha=0.95, fontsize=9.5,
    )
    _add_scale_bar(ax1, bbox, length_km=5.0)

    # ----- Panel 2: GAPS AFTER (with new tower pins, no radius - kept clean) ---
    ax2 = fig.add_subplot(gs[1, 1])
    _try_add_basemap(ax2, bbox, alpha=0.95)
    o2 = _mask_overlay(after_stats['gap_mask'], GAP_COLOR, alpha=0.55)
    ax2.imshow(o2, origin='lower', extent=extent,
               aspect='auto', interpolation='nearest', zorder=2)
    for i, t in enumerate(new_towers, start=1):
        _draw_tower_pin(ax2, t['lon'], t['lat'], label=str(i),
                        size=24, show_radius=False)
    _style_map_axes(ax2, bbox, show_labels=False)
    ax2.set_title(f'AFTER  ·  {after_stats["gap_area_km2"]:.0f} km² remain',
                  loc='left', fontsize=12)
    ax2.legend(
        handles=[
            mpatches.Patch(color=GAP_COLOR, alpha=0.55, label='Remaining gap'),
            plt.Line2D([0], [0], marker='o', color='w',
                       markerfacecolor=PIN_COLOR, markeredgecolor='white',
                       markeredgewidth=1.5, markersize=11,
                       label='New tower'),
        ],
        loc='upper left', framealpha=0.95, fontsize=9.5,
    )

    # ----- Panel 3: IMPROVEMENT (delta map - the money shot) ---------------
    ax3 = fig.add_subplot(gs[1, 2])
    _try_add_basemap(ax3, bbox, alpha=0.95)

    fixed_mask = (before_grid == 0) & (after_grid >= 1)
    redundancy_mask = (after_grid > before_grid) & (before_grid > 0)
    # Redundancy first (cyan, lower visual weight) so green (gap-fix) wins on overlap
    if redundancy_mask.any():
        ax3.imshow(_mask_overlay(redundancy_mask, REDUNDANCY_COLOR, 0.55),
                   origin='lower', extent=extent, aspect='auto',
                   interpolation='nearest', zorder=2)
    if fixed_mask.any():
        ax3.imshow(_mask_overlay(fixed_mask, GAP_FIXED_COLOR, 0.95),
                   origin='lower', extent=extent, aspect='auto',
                   interpolation='nearest', zorder=3)
    for i, t in enumerate(new_towers, start=1):
        radius_deg = t['radius'] / (EARTH_RADIUS_M * np.pi / 180)
        _draw_tower_pin(ax3, t['lon'], t['lat'], label=str(i),
                        radius_deg=radius_deg,
                        size=24, show_radius=True)
    _style_map_axes(ax3, bbox, show_labels=False)
    ax3.set_title('IMPROVEMENT  ·  green = gap → covered · cyan = added redundancy',
                  loc='left', fontsize=12)
    ax3.legend(
        handles=[
            mpatches.Patch(color=GAP_FIXED_COLOR, alpha=0.95,
                            label='Gap → covered'),
            mpatches.Patch(color=REDUNDANCY_COLOR, alpha=0.55,
                            label='Added redundancy'),
            plt.Line2D([0], [0], marker='o', color='w',
                       markerfacecolor=PIN_COLOR, markeredgecolor='white',
                       markeredgewidth=1.5, markersize=11,
                       label='New tower (dashed = radius)'),
        ],
        loc='upper left', framealpha=0.95, fontsize=9.5,
    )
    _add_north_arrow(ax3, bbox)

    # ----- Bottom row: per-tower bar chart + KPI cards ---------------------
    bottom = gs[2, :].subgridspec(nrows=1, ncols=2,
                                  width_ratios=[1.4, 2.6], wspace=0.12)

    # Per-tower contribution bar (sorted descending)
    ax_bars = fig.add_subplot(bottom[0, 0])
    if per_tower:
        pairs = sorted(enumerate(per_tower, start=1),
                       key=lambda p: -p[1])
        idxs = [p[0] for p in pairs]
        vals = [p[1] for p in pairs]
        y_pos = np.arange(len(idxs))[::-1]
        bars = ax_bars.barh(y_pos, vals, color=GAP_FIXED_COLOR,
                            edgecolor='white', linewidth=0.8)
        max_val = max(vals) if vals else 1.0
        for bar, val in zip(bars, vals):
            ax_bars.text(bar.get_width() + max_val * 0.02,
                          bar.get_y() + bar.get_height() / 2,
                          f'{val:.2f} km²', va='center',
                          fontsize=9, color='#2c3e50')
        ax_bars.set_yticks(y_pos)
        ax_bars.set_yticklabels([f'#{i}' for i in idxs], fontsize=9)
        ax_bars.set_xlabel('Gap reduction · standalone (km²)', fontsize=9)
        ax_bars.set_title('Per-tower contribution · ranked',
                           loc='left', fontsize=11)
        ax_bars.set_xlim(0, max_val * 1.20 if max_val > 0 else 1.0)
        ax_bars.spines['top'].set_visible(False)
        ax_bars.spines['right'].set_visible(False)
    else:
        ax_bars.axis('off')
        ax_bars.text(0.5, 0.5, 'no per-tower contribution data',
                     ha='center', va='center', fontsize=10,
                     color='#7f8c8d')

    # KPI cards on the right
    ax_kpi = fig.add_subplot(bottom[0, 1])
    fixed_count = int(fixed_mask.sum())
    redundancy_count = int(redundancy_mask.sum())
    cards = [
        ('GAP REDUCTION', f'-{delta_km2:.1f} km²', KPI_GOOD,
            f'{delta_pct:.1f}% improvement'),
        ('CELLS FIXED',   f'{fixed_count:,}', KPI_GOOD,
            'gap → covered'),
        ('NEW REDUNDANCY', f'{redundancy_count:,}', KPI_ACCENT,
            'cells with extra tower'),
        ('NEW TOWERS',    f'{len(new_towers)}', KPI_ACCENT,
            f'LTE · {new_towers[0]["radius"]:.0f} m radius'),
    ]
    _kpi_strip(ax_kpi, cards)
    return fig
