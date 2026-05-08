import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.figure
import matplotlib.colors as mcolors
import folium

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import GRID_RESOLUTION, BBOX


RADIO_COLORS = {
    'GSM':  '#3388ff',
    'UMTS': '#ff7800',
    'LTE':  '#00aa00',
    'NR':   '#aa00aa',
}


# ---------------------------------------------------------------------------
# Belso segedfüggvenyek
# ---------------------------------------------------------------------------

def _try_add_basemap(ax, bbox: dict, alpha: float = 0.85) -> None:
    """Add OSM basemap tiles under the axes (zorder=0). Silently skips on failure."""
    try:
        import contextily as ctx
        ax.set_xlim(bbox['lon_min'], bbox['lon_max'])
        ax.set_ylim(bbox['lat_min'], bbox['lat_max'])
        ctx.add_basemap(
            ax,
            crs='EPSG:4326',
            source=ctx.providers.OpenStreetMap.Mapnik,
            zorder=0,
            alpha=alpha,
        )
    except Exception:
        pass


def _log_norm(vmax: int) -> mcolors.LogNorm:
    """LogNorm for the 1..vmax range."""
    return mcolors.LogNorm(vmin=1, vmax=max(int(vmax), 2))


def _coverage_rgba(coverage: np.ndarray, cmap_name: str,
                   vmax: int, max_alpha: float = 0.88) -> np.ndarray:
    """
    Build an RGBA array with gradual log-scaled alpha:
      coverage == 0    -> alpha = 0.0       (fully transparent, basemap visible)
      coverage == 1    -> alpha ~ 0.08      (barely tinted, basemap visible)
      coverage middle  -> alpha ~ 0.45
      coverage == vmax -> alpha = max_alpha (full color)

    Sparsely covered suburbs stay almost transparent;
    dense city centers get the full color.
    """
    cmap = plt.cm.get_cmap(cmap_name)
    norm = _log_norm(vmax)
    colored = cmap(norm(coverage.clip(min=1))).astype(float)

    # log1p(c) / log1p(vmax) : 0->0, 1->small, vmax->1
    vmax_safe = max(int(vmax), 2)
    log_ratio = np.where(
        coverage > 0,
        np.log1p(coverage.astype(float)) / np.log1p(vmax_safe),
        0.0,
    )
    colored[..., 3] = np.clip(log_ratio * max_alpha, 0.0, max_alpha)
    return colored


def _scalar_mappable(cmap_name: str, vmax: int):
    """ScalarMappable for the colorbar (log scale)."""
    sm = plt.cm.ScalarMappable(cmap=plt.cm.get_cmap(cmap_name), norm=_log_norm(vmax))
    sm.set_array([])
    return sm


def _add_coverage_imshow(ax, coverage, bbox, max_alpha=0.88):
    """Coverage RGBA overlay with gradual log alpha."""
    vmax = int(coverage.max())
    extent = [bbox['lon_min'], bbox['lon_max'], bbox['lat_min'], bbox['lat_max']]
    rgba = _coverage_rgba(coverage, 'YlOrRd', vmax, max_alpha=max_alpha)
    ax.imshow(rgba, origin='lower', extent=extent,
              aspect='auto', interpolation='nearest', zorder=2)
    return vmax


# ---------------------------------------------------------------------------
# Folium interactive map (HTML output)
# ---------------------------------------------------------------------------

def create_folium_map(towers_df: pd.DataFrame, coverage: np.ndarray,
                      grid_lat: np.ndarray, grid_lon: np.ndarray, stats: dict) -> folium.Map:
    """Build an interactive folium map with heatmap, gap markers and tower markers."""
    m = folium.Map(location=[47.5, 19.1], zoom_start=11, tiles='OpenStreetMap')

    H, W = coverage.shape

    # Coverage raszter overlay: a 2D gridet RGBA kepkent rakjuk a terkepre.
    # Igy a fedettség a koordinatakhoz van rogzitve es zoom-on simán skalazodik
    # (ellentetben a folium HeatMap pluginnal, ami pixelben dolgozik es csempes mintat ad).
    vmax = int(coverage.max())
    rgba = _coverage_rgba(coverage, 'YlOrRd', vmax, max_alpha=0.75)
    rgba_img = np.flipud(rgba)  # ImageOverlay: north-up; a coverage [0,0] = south-west
    bounds = [[float(grid_lat[0, 0]),  float(grid_lon[0, 0])],
              [float(grid_lat[-1, 0]), float(grid_lon[0, -1])]]
    folium.raster_layers.ImageOverlay(
        image=rgba_img,
        bounds=bounds,
        opacity=1.0,  # az alpha mar bele van kodolva az RGBA-ba
        name='Coverage',
        interactive=False,
        cross_origin=False,
        mercator_project=True,
    ).add_to(m)

    # Gap markers: minden 5. cellat mintavetelezunk (suruseg-csokkentes)
    gap_group = folium.FeatureGroup(name='Gap areas')
    gap_mask = stats['gap_mask']
    sub_mask = gap_mask[::5, ::5]
    gap_lats = grid_lat[::5, ::5][sub_mask]
    gap_lons = grid_lon[::5, ::5][sub_mask]
    for lat, lon in zip(gap_lats, gap_lons):
        folium.CircleMarker(
            location=[lat, lon],
            radius=3, color='red', fill=True,
            fill_opacity=0.5, weight=0,
        ).add_to(gap_group)
    gap_group.add_to(m)

    tower_group = folium.FeatureGroup(name='Towers')
    sample_df = towers_df if len(towers_df) <= 5000 else towers_df.sample(2000, random_state=42)
    for _, row in sample_df.iterrows():
        color = RADIO_COLORS.get(row['radio'], '#888888')
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=4, color=color, fill=True, fill_opacity=0.7,
            popup=f"{row['radio']} | r={row.get('radius', 300):.0f}m",
        ).add_to(tower_group)
    tower_group.add_to(m)

    folium.LayerControl().add_to(m)

    info_html = f"""
    <div style="position:fixed; top:10px; left:50px; z-index:1000;
                background:white; padding:10px; border-radius:8px;
                box-shadow:2px 2px 6px rgba(0,0,0,0.3); font-size:13px;">
      <b>Budapest Mobile Network</b><br>
      Towers: {len(towers_df):,}<br>
      Coverage: {(1 - stats['gap_fraction']) * 100:.1f}%<br>
      Gap area: {stats['gap_area_km2']:.1f} km&sup2;<br>
      Avg towers/cell: {stats['mean_coverage']:.2f}
    </div>"""
    m.get_root().html.add_child(folium.Element(info_html))
    return m


# ---------------------------------------------------------------------------
# Heatmap figure - 2 panels (coverage + gap categories)
# ---------------------------------------------------------------------------

def create_heatmap_figure(coverage: np.ndarray, bbox: dict, stats: dict,
                          towers_df: pd.DataFrame) -> matplotlib.figure.Figure:
    """Two-panel matplotlib figure: coverage heatmap + gap/overlap categories."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6.5), layout='constrained')

    extent = [bbox['lon_min'], bbox['lon_max'], bbox['lat_min'], bbox['lat_max']]
    vmax = int(coverage.max())

    # --- Left panel: coverage count (log scale, gradual alpha) ---
    _add_coverage_imshow(ax1, coverage, bbox, max_alpha=0.88)
    fig.colorbar(_scalar_mappable('YlOrRd', vmax), ax=ax1, shrink=0.85,
                 label='Towers per cell (log)')
    _try_add_basemap(ax1, bbox)
    ax1.set_xlim(bbox['lon_min'], bbox['lon_max'])
    ax1.set_ylim(bbox['lat_min'], bbox['lat_max'])
    ax1.set_title(
        f'Mobile Network Coverage - Budapest\n'
        f'{len(towers_df):,} towers | {GRID_RESOLUTION}x{GRID_RESOLUTION} grid'
    )
    ax1.set_xlabel('Longitude')
    ax1.set_ylabel('Latitude')

    # --- Right panel: gap / well-served / overlap categories ---
    gap_display = np.zeros_like(coverage, dtype=float)
    gap_display[stats['gap_mask']]         = 1.0   # piros = gap
    gap_display[stats['well_served_mask']] = 0.5   # sarga = 1 torony
    gap_display[stats['overlap_mask']]     = 0.0   # zold  = jo fedettség

    cmap_cat = plt.cm.RdYlGn_r
    rgba2 = cmap_cat(gap_display).astype(float)
    rgba2[..., 3] = 0.70
    ax2.imshow(rgba2, origin='lower', extent=extent, aspect='auto', zorder=2)

    sm2 = plt.cm.ScalarMappable(cmap=cmap_cat,
                                 norm=mcolors.Normalize(vmin=0, vmax=1))
    sm2.set_array([])
    cb2 = fig.colorbar(sm2, ax=ax2, shrink=0.85)
    cb2.set_ticks([0.0, 0.5, 1.0])
    cb2.set_ticklabels(['Good (>=2 towers)', '1 tower', 'Gap (0 towers)'])

    _try_add_basemap(ax2, bbox)
    ax2.set_xlim(bbox['lon_min'], bbox['lon_max'])
    ax2.set_ylim(bbox['lat_min'], bbox['lat_max'])
    ax2.set_title(
        f'Coverage categories\n'
        f'Gap: {stats["gap_area_km2"]:.1f} km2 '
        f'({stats["gap_fraction"] * 100:.1f}%) | '
        f'Overlap: {stats["overlap_area_km2"]:.1f} km2'
    )
    ax2.set_xlabel('Longitude')
    ax2.set_ylabel('Latitude')

    return fig


# ---------------------------------------------------------------------------
# Simulation figure - 3 panels (before / after / difference)
# ---------------------------------------------------------------------------

def create_simulation_figure(sim_results: dict, grid_lat: np.ndarray,
                              grid_lon: np.ndarray, bbox: dict) -> matplotlib.figure.Figure:
    """Three-panel figure showing the effect of hypothetical new towers."""
    before_grid  = sim_results['original_grid']
    after_grid   = sim_results['new_coverage_grid']
    new_towers   = sim_results['new_towers']
    before_stats = sim_results['before']
    after_stats  = sim_results['after']

    fig, axes = plt.subplots(1, 3, figsize=(19, 6.5), layout='constrained')
    extent = [bbox['lon_min'], bbox['lon_max'], bbox['lat_min'], bbox['lat_max']]
    vmax = max(int(before_grid.max()), int(after_grid.max()), 2)

    def _panel(ax, grid, title):
        rgba = _coverage_rgba(grid, 'YlOrRd', vmax, max_alpha=0.88)
        ax.imshow(rgba, origin='lower', extent=extent, aspect='auto', zorder=2)
        fig.colorbar(_scalar_mappable('YlOrRd', vmax), ax=ax,
                     label='Towers (log)', shrink=0.85)
        _try_add_basemap(ax, bbox)
        ax.set_xlim(bbox['lon_min'], bbox['lon_max'])
        ax.set_ylim(bbox['lat_min'], bbox['lat_max'])
        ax.set_title(title)
        ax.set_xlabel('Longitude')

    # Panel 1 - Before
    _panel(axes[0], before_grid,
           f'Before\nCoverage: {(1-before_stats["gap_fraction"])*100:.1f}%  |  '
           f'Gap: {before_stats["gap_area_km2"]:.1f} km2')
    axes[0].set_ylabel('Latitude')

    # Panel 2 - After + uj tornyok cyan csillaggal
    _panel(axes[1], after_grid,
           f'After ({len(new_towers)} new towers)\n'
           f'Coverage: {(1-after_stats["gap_fraction"])*100:.1f}%  |  '
           f'Gap: {after_stats["gap_area_km2"]:.1f} km2')
    for t in new_towers:
        axes[1].plot(t['lon'], t['lat'],
                     marker='*', markersize=14, color='cyan',
                     markeredgecolor='black', zorder=5)

    # Panel 3 - Difference (uj fedettség zolden)
    diff = after_grid.astype(np.int32) - before_grid.astype(np.int32)
    diff_pos = diff.clip(min=0)
    dmax = max(int(diff_pos.max()), 2)
    rgba_d = _coverage_rgba(diff_pos, 'Greens', dmax, max_alpha=0.88)
    axes[2].imshow(rgba_d, origin='lower', extent=extent, aspect='auto', zorder=2)
    fig.colorbar(_scalar_mappable('Greens', dmax), ax=axes[2],
                 label='Newly covered cells (log)', shrink=0.85)
    _try_add_basemap(axes[2], bbox)
    axes[2].set_xlim(bbox['lon_min'], bbox['lon_max'])
    axes[2].set_ylim(bbox['lat_min'], bbox['lat_max'])
    axes[2].set_title(
        f'Difference (new coverage)\n'
        f'Gap reduction: {sim_results["gap_reduction_km2"]:.2f} km2  '
        f'({sim_results["gap_reduction_pct"]:.1f}%)'
    )
    axes[2].set_xlabel('Longitude')

    fig.suptitle(
        f'Tower Simulation  |  Gap reduction: '
        f'{sim_results["gap_reduction_km2"]:.2f} km2 '
        f'({sim_results["gap_reduction_pct"]:.1f}%)  |  '
        f'New towers: {len(new_towers)}',
        fontsize=13, fontweight='bold',
    )
    return fig
