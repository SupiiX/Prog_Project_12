# Project 12 – Mobile Tower Coverage Mapper
## Claude Code Implementation Specification

Ez a fájl a teljes technikai terv. Claude Code ezt olvassa és ez alapján implementálja a projektet.
Minden döntés, algoritmus, interfész és edge case itt van definiálva.

---

## 1. PROJEKT ÁTTEKINTÉS

**Cél:** Mobilcellák lefedettségét elemezzük Budapest területén az OpenCelliD adathalmaz
alapján. Raszteres gridet készítünk, hőtérképet rajzolunk, megtaláljuk a lefedetlen (gap)
területeket, majd szimulálunk új torony-elhelyezéseket.

**Bemenet:** `data/raw/cell_towers.csv.gz` – OpenCelliD teljes Magyarország adatbázis
**Kimenetek:** `output/coverage_map.html`, `output/heatmap.png`, `output/gap_analysis.png`,
             `output/simulation_report.png`

---

## 2. KÖNYVTÁRSZERKEZET

Pontosan ezt a struktúrát kell létrehozni:

```
project_12/
├── CLAUDE.md                   ← ez a fájl
├── requirements.txt
├── config.py                   ← minden konstans itt van, NEM hardcode-olva máshol
├── main.py                     ← belépési pont, orchestrátor
├── src/
│   ├── __init__.py             ← üres
│   ├── data_loader.py          ← CSV betöltés, szűrés, tisztítás
│   ├── signal_model.py         ← sugár becslési logika
│   ├── rasterizer.py           ← grid + coverage counting
│   ├── gap_analyzer.py         ← gap detekció, statisztikák
│   ├── visualizer.py           ← folium térkép + matplotlib ábrák
│   └── simulator.py            ← új torony szimulálás
├── data/
│   ├── raw/                    ← ide kerül a letöltött cell_towers.csv.gz
│   └── processed/              ← közbenső fájlok (auto-generált)
└── output/                     ← minden végeredmény ide kerül
```

A `data/raw/`, `data/processed/`, `output/` mappákat a `main.py` hozza létre
`os.makedirs(..., exist_ok=True)` hívással az elején.

---

## 3. REQUIREMENTS.TXT

```
pandas>=2.0.0
numpy>=1.24.0
shapely>=2.0.0
folium>=0.14.0
matplotlib>=3.7.0
scipy>=1.10.0
tqdm>=4.65.0
```

**Miért nincs geopandas és requests?**
- `geopandas`: A projekt pandas+numpy+shapely alapon teljesíti a feladatot.
  geopandas nem szükséges – a shapely-t közvetlenül hívjuk.
- `requests`: Az adatletöltés kézi lépés (browser, API key kell) – nem automatizált.

Telepítés: `pip install -r requirements.txt --break-system-packages`

---

## 4. CONFIG.PY – MINDEN KONSTANS

```python
# config.py

# Város és bounding box
CITY = "Budapest"
BBOX = {
    'lat_min': 47.35,
    'lat_max': 47.65,
    'lon_min': 18.85,
    'lon_max': 19.35
}

# OpenCelliD
MCC = 216  # Magyarország country code

# Grid felbontás
GRID_RESOLUTION = 500  # 500x500 cella → ~100m x ~100m cellaméret Budapesten

# Sugár korlátok
MAX_RADIUS_M = 5000       # max elfogadott sugár méterben (outlier szűrés)
MIN_RADIUS_M = 50         # min sugár méterben

# Default sugarak rádiótípusonként (ha nincs jobb adat)
DEFAULT_RADII_M = {
    'GSM':  1000,
    'UMTS':  500,
    'LTE':   300,
    'NR':    150,
}

# Path loss modell (log-distance)
TX_POWER_DBM = 43           # tipikus torony adási teljesítmény
PATH_LOSS_EXPONENT = 3.5    # városi szórási együttható
REF_DISTANCE_M = 100        # referencia távolság
FREQ_MHZ = {                # tipikus frekvenciák rádiótípusonként
    'GSM':  900,
    'UMTS': 2100,
    'LTE':  1800,
    'NR':   3500,
}

# Föld sugara
EARTH_RADIUS_M = 6_371_000

# Fájl útvonalak
RAW_DATA_PATH      = 'data/raw/cell_towers.csv.gz'
PROCESSED_PATH     = 'data/processed/towers_processed.csv'
COVERAGE_GRID_PATH = 'data/processed/coverage_grid.npy'
OUTPUT_MAP_HTML    = 'output/coverage_map.html'
OUTPUT_HEATMAP_PNG = 'output/heatmap.png'
OUTPUT_GAP_PNG     = 'output/gap_analysis.png'
OUTPUT_SIM_PNG     = 'output/simulation_report.png'

# Szimuláció – kézi toronyhelyek (üres = automatikus gap-klaszter alapú)
# Formátum: [{'lat': 47.50, 'lon': 19.05, 'radius': 300, 'radio': 'LTE'}, ...]
MANUAL_NEW_TOWERS = []
```

---

## 5. SRC/DATA_LOADER.PY

### Függvények

#### `load_towers(filepath, bbox, mcc) -> pd.DataFrame`

**Cél:** Nagy CSV fájl chunk-onkénti betöltése, MCC és bounding box szűrés.

**Logika:**
```
1. Ellenőrizd, hogy a fájl létezik-e. Ha nem: FileNotFoundError dobás,
   hasznos üzenettel: "Töltsd le az OpenCelliD adatbázist: ..."

2. Csak ezeket az oszlopokat olvasd be (usecols):
   ['radio', 'mcc', 'lon', 'lat', 'range', 'averageSignal']
   → Ez csökkenti a memória-igényt

3. Chunked olvasás (chunksize=100_000):
   - Szűrés: chunk['mcc'] == mcc
   - Szűrés: lat és lon bounding box-on belül
   - Összes szűrt chunk -> list -> pd.concat

4. Ha az eredmény üres DataFrame: ValueError dobás,
   üzenet: "Nem találtunk tornyot a megadott területen."

5. Visszatér: szűrt, nyers DataFrame
```

**Fontos részletek:**
- A `range` oszlop neve Python-ban ütközik a beépített `range` függvénnyel,
  ezért mindig idézőjelben: `df['range']`
- A fájl lehet `.csv` vagy `.csv.gz` – a pandas mindkettőt kezeli automatikusan

#### `clean_towers(df) -> pd.DataFrame`

**Cél:** Adattisztítás a betöltés után.

**Lépések sorrendben:**
```
1. Eldobja a sorokat ahol lat vagy lon NaN
2. Eldobja a sorokat ahol lat nem (-90, 90) között, lon nem (-180, 180)
3. ismeretlen radio típusok kezelése:
   - Ha nem 'GSM', 'UMTS', 'LTE', 'NR': legyen 'LTE' (leggyakoribb)
4. range értékek: ha range <= 0 vagy NaN: legyen 0 (később kezeljük)
5. averageSignal: ha NaN: legyen 0
6. Duplikátumok eltávolítása: lat+lon+radio kombináció alapján
7. Index reset
```

**Visszatér:** tiszta DataFrame

#### `save_processed(df, path)`
Egyszerű `df.to_csv(path, index=False)` – szükség esetén a processed mappa
létrehozásával.

---

## 6. SRC/SIGNAL_MODEL.PY

### A sugár becslési prioritás logika

**Minden toronyhoz** egyetlen `radius` értéket számolunk (méterben, float).
Három prioritási szint:

```
PRIORITÁS 1 – OpenCelliD range mező:
  Ha 0 < df['range'] < MAX_RADIUS_M * 3:  (3x MAX azért, mert vidéken nagyobb lehet)
    radius = min(df['range'], MAX_RADIUS_M)
  → Ez a legjobb forrás, az OpenCelliD már megbecsülte a tényleges lefedést

PRIORITÁS 2 – averageSignal alapú becslés:
  Ha df['averageSignal'] != 0:
    radius = _path_loss_radius(signal_dbm, radio_type)
  → Log-distance path loss modell

PRIORITÁS 3 – Default rádiótípus szerint:
  radius = DEFAULT_RADII_M.get(radio_type, 500)
```

#### `estimate_radii(df) -> pd.Series`

**FONTOS:** Nem sorról sorra (apply), hanem vektorizáltan!

```python
def estimate_radii(df: pd.DataFrame) -> pd.Series:
    """
    Vektorizált sugár becslés. Visszatér: pd.Series float méterben.
    """
    radii = pd.Series(index=df.index, dtype=float)
    
    # Prioritás 3: default (alap)
    radii = df['radio'].map(DEFAULT_RADII_M).fillna(500.0)
    
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
    
    # Végső clip
    return radii.clip(lower=MIN_RADIUS_M, upper=MAX_RADIUS_M)
```

#### `_path_loss_radius_vectorized(signal_series, radio_series) -> pd.Series`

**Algoritmus – Log-distance path loss modell:**

```
PL(d0) = 20*log10(d0) + 20*log10(f_hz) - 147.55
         ahol f_hz = FREQ_MHZ[radio] * 1e6, d0 = REF_DISTANCE_M

d = d0 * 10^( (Pt - Pr - PL(d0)) / (10 * n) )
    ahol Pt = TX_POWER_DBM
         Pr = averageSignal (negatív dBm)
         n  = PATH_LOSS_EXPONENT
```

**Python implementáció:**
```python
import numpy as np
from config import *

def _path_loss_radius_vectorized(signal_series, radio_series):
    freq_hz = radio_series.map(FREQ_MHZ).fillna(1800) * 1e6
    pl_d0 = (20 * np.log10(REF_DISTANCE_M) +
             20 * np.log10(freq_hz) - 147.55)
    exponent = (TX_POWER_DBM - signal_series - pl_d0) / (10 * PATH_LOSS_EXPONENT)
    radii = REF_DISTANCE_M * np.power(10.0, exponent)
    return radii.clip(lower=MIN_RADIUS_M, upper=MAX_RADIUS_M)
```

---

## 7. SRC/RASTERIZER.PY

### Kulcsfogalom

A grid egy `(GRID_RESOLUTION, GRID_RESOLUTION)` alakú 2D numpy tömb.
- Sor index = szélességi fok (lat) irány: 0. sor = lat_min, utolsó sor = lat_max
- Oszlop index = hosszúsági fok (lon) irány: 0. oszlop = lon_min, utolsó oszlop = lon_max
- `coverage[i, j]` = hány torony fedi le az (i, j) rácspontot

### `create_grid(bbox, resolution) -> tuple[np.ndarray, np.ndarray]`

```python
def create_grid(bbox, resolution):
    lats = np.linspace(bbox['lat_min'], bbox['lat_max'], resolution)
    lons = np.linspace(bbox['lon_min'], bbox['lon_max'], resolution)
    grid_lat, grid_lon = np.meshgrid(lats, lons, indexing='ij')
    # grid_lat.shape == grid_lon.shape == (resolution, resolution)
    return grid_lat, grid_lon
```

### `rasterize_coverage(towers_df, grid_lat, grid_lon) -> np.ndarray`

**Algoritmus – Spatially-indexed flat-earth távolság:**

Naiv megközelítés (minden torony × minden cella) 500x500 griden 10000 toronnyal:
500×500×10000 = 2.5 milliárd művelet → túl lassú.

**Optimalizált megközelítés:** Minden toronyhoz csak a körülötte lévő cellákat vizsgáljuk
(bounding box előszűrés). Ez tipikusan 10-100x gyorsabb.

```python
def rasterize_coverage(towers_df, grid_lat, grid_lon):
    H, W = grid_lat.shape
    coverage = np.zeros((H, W), dtype=np.int16)
    
    # Grid lépések
    dlat = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)
    lat0 = grid_lat[0, 0]
    lon0 = grid_lon[0, 0]
    
    R = EARTH_RADIUS_M
    
    for _, tower in tqdm(towers_df.iterrows(), total=len(towers_df),
                         desc="Raszterizálás"):
        r = tower['radius']
        tlat = tower['lat']
        tlon = tower['lon']
        
        # Sugár fokokban (bounding box előszűréshez)
        r_lat_deg = r / (R * np.pi / 180)
        r_lon_deg = r / (R * np.pi / 180 * np.cos(np.radians(tlat)))
        
        # Grid index tartomány
        lat_lo = max(0,   int((tlat - r_lat_deg - lat0) / dlat))
        lat_hi = min(H,   int((tlat + r_lat_deg - lat0) / dlat) + 2)
        lon_lo = max(0,   int((tlon - r_lon_deg - lon0) / dlon))
        lon_hi = min(W,   int((tlon + r_lon_deg - lon0) / dlon) + 2)
        
        # Részgrid
        sub_lat = grid_lat[lat_lo:lat_hi, lon_lo:lon_hi]
        sub_lon = grid_lon[lat_lo:lat_hi, lon_lo:lon_hi]
        
        # Flat-earth távolság (méterben) – pontos < 15 km-es sugarakra
        dlat_m = (sub_lat - tlat) * R * np.pi / 180
        dlon_m = (sub_lon - tlon) * R * np.pi / 180 * np.cos(np.radians(tlat))
        dist_m = np.sqrt(dlat_m**2 + dlon_m**2)
        
        # Fedettség növelése
        coverage[lat_lo:lat_hi, lon_lo:lon_hi] += (dist_m <= r).astype(np.int16)
    
    return coverage
```

**Mentés:** `np.save(COVERAGE_GRID_PATH, coverage)` – újrafuttatáskor betölthető.

**Újrabetöltés gyorsításhoz:** A main.py ellenőrizze: ha a processed fájl már létezik
és a towers fájl nem változott (mtime alapján), töltse be a cache-ből és skip-elje
a raszterizálást.

---

## 8. SRC/GAP_ANALYZER.PY

### `analyze_gaps(coverage, grid_lat, grid_lon) -> dict`

**Visszatér:** dictionary az alábbi kulcsokkal:

```python
{
    'gap_mask':          np.ndarray bool,  # True ahol coverage == 0
    'overlap_mask':      np.ndarray bool,  # True ahol coverage >= 2
    'well_served_mask':  np.ndarray bool,  # True ahol coverage == 1
    'gap_cells':         int,
    'gap_area_km2':      float,
    'gap_fraction':      float,            # 0..1
    'overlap_cells':     int,
    'overlap_area_km2':  float,
    'overlap_fraction':  float,
    'mean_coverage':     float,
    'max_coverage':      int,
    'cell_area_km2':     float,
    'total_area_km2':    float,
}
```

**Cellaméret számítás:**
```python
# A grid közepes szélességén számoljuk (Budapestnél ~47.5°)
center_lat = grid_lat.mean()
dlat_deg = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
dlon_deg = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)

# Méterbe konverzió
dlat_m = dlat_deg * EARTH_RADIUS_M * np.pi / 180
dlon_m = dlon_deg * EARTH_RADIUS_M * np.pi / 180 * np.cos(np.radians(center_lat))
cell_area_km2 = (dlat_m * dlon_m) / 1e6
```

### `find_gap_clusters(gap_mask, grid_lat, grid_lon, top_n=10) -> list[dict]`

A gap területeket összefüggő régiókba csoportosítja, hogy megtaláljuk
a legjobb új torony-elhelyezési pontokat.

**Algoritmus:**
```python
from scipy.ndimage import label, center_of_mass

def find_gap_clusters(gap_mask, grid_lat, grid_lon, top_n=10):
    labeled_array, num_features = label(gap_mask)
    
    clusters = []
    for region_id in range(1, num_features + 1):
        region_mask = (labeled_array == region_id)
        size = region_mask.sum()
        cy, cx = center_of_mass(region_mask)
        # Interpoláljuk a centroid koordinátát
        lat = grid_lat[int(round(cy)), int(round(cx))]
        lon = grid_lon[int(round(cy)), int(round(cx))]
        clusters.append({'lat': lat, 'lon': lon, 'size_cells': size})
    
    # Méret szerint csökkenő sorrendben, top_n visszaadása
    clusters.sort(key=lambda x: -x['size_cells'])
    return clusters[:top_n]
```

---

## 9. SRC/VISUALIZER.PY

### `create_folium_map(towers_df, coverage, grid_lat, grid_lon, stats) -> folium.Map`

**Térképrétegek (ebben a sorrendben):**

1. **Base layer:** `folium.Map(location=[47.5, 19.1], zoom_start=11, tiles='OpenStreetMap')`

2. **Coverage heatmap réteg:**
   - A `coverage` gridet konvertáld pontlistává: `[[lat, lon, weight], ...]`
   - Csak ahol coverage > 0
   - `weight = min(coverage[i,j] / 5.0, 1.0)` – normalizálva 0..1-re
   - `folium.plugins.HeatMap(data, name='Lefedettség', min_opacity=0.3,
                             radius=15, blur=20)`

3. **Gap réteg (piros overlay):**
   - Gap cellákat aggregáld téglalap poligonokba (túl sok egyedi cella lenne)
   - Egyszerűbb megközelítés: `folium.plugins.HeatMap` a gap pontokra
     külön rétegen piros színezéssel
   - Vagy: mintavételezd le a gap cellákat (minden 5. sort/oszlopot), add hozzá
     `CircleMarker(radius=3, color='red', fill=True, fill_opacity=0.4)`

4. **Torony markerek:**
   - Színek rádiótípusonként:
     ```
     GSM  → '#3388ff' (kék)
     UMTS → '#ff7800' (narancs)
     LTE  → '#00aa00' (zöld)
     NR   → '#aa00aa' (lila)
     ```
   - `folium.CircleMarker(location=[lat, lon], radius=4, color=szin,
                          fill=True, fill_opacity=0.7,
                          popup=f"{radio} | r={radius:.0f}m")`
   - Ha sok torony van (>5000), mintavételezd le (random 2000-t)

5. **Layer control:** `folium.LayerControl().add_to(m)`

6. **Statisztika info box** (bal felső sarokba):
   ```python
   info_html = f"""
   <div style="position:fixed; top:10px; left:50px; z-index:1000;
               background:white; padding:10px; border-radius:8px;
               box-shadow:2px 2px 6px rgba(0,0,0,0.3); font-size:13px;">
     <b>Budapest Mobilhálózat</b><br>
     Tornyok: {len(towers_df):,}<br>
     Fedettség: {(1-stats['gap_fraction'])*100:.1f}%<br>
     Gap terület: {stats['gap_area_km2']:.1f} km²<br>
     Átlagos torony/cella: {stats['mean_coverage']:.2f}
   </div>"""
   m.get_root().html.add_child(folium.Element(info_html))
   ```

### `create_heatmap_figure(coverage, bbox, stats, towers_df) -> matplotlib.figure.Figure`

**2 subplot egymás mellett (1 sor, 2 oszlop), figsize=(14, 6):**

**Bal panel – Coverage heatmap:**
```python
im = ax1.imshow(coverage, origin='lower', cmap='YlOrRd',
                extent=[bbox['lon_min'], bbox['lon_max'],
                        bbox['lat_min'], bbox['lat_max']],
                aspect='auto', interpolation='nearest')
plt.colorbar(im, ax=ax1, label='Tornyok száma')
ax1.set_title(f'Mobilhálózat lefedettség – Budapest\n'
              f'({len(towers_df):,} torony, {GRID_RESOLUTION}×{GRID_RESOLUTION} grid)')
ax1.set_xlabel('Hosszúság (°)')
ax1.set_ylabel('Szélesség (°)')
```

**Jobb panel – Gap térkép:**
```python
gap_display = np.zeros_like(coverage, dtype=float)
gap_display[stats['gap_mask']] = 1.0         # piros = gap
gap_display[stats['well_served_mask']] = 0.5  # sárga = 1 torony
gap_display[stats['overlap_mask']] = 0.0      # zöld = jó fedettség

cmap_custom = plt.cm.RdYlGn_r
im2 = ax2.imshow(gap_display, origin='lower', cmap=cmap_custom,
                 extent=[bbox['lon_min'], bbox['lon_max'],
                         bbox['lat_min'], bbox['lat_max']],
                 vmin=0, vmax=1, aspect='auto')
ax2.set_title(f'Fedettségi kategóriák\n'
              f'Gap: {stats["gap_area_km2"]:.1f} km² '
              f'({stats["gap_fraction"]*100:.1f}%)')
```

**Tight layout + mentés:** `fig.savefig(OUTPUT_HEATMAP_PNG, dpi=150, bbox_inches='tight')`

### `create_gap_analysis_figure(coverage, stats, clusters, grid_lat, grid_lon) -> Figure`

**Egyetlen ábra, figsize=(10, 8):**
- Alap: coverage heatmap szürke skálán
- Gap területek piros overlay-jel
- Javasolt új torony helyek: sárga csillag marker (`marker='*'`, `markersize=15`,
  `color='yellow'`, `edgecolor='black'`, `zorder=5`)
- Felirat minden javasolt helynél: `ax.annotate(f'#{i+1}', (lon, lat), ...)`

---

## 10. SRC/SIMULATOR.PY

### Hipotetikus toronyok generálása

**Automatikus generálás** a gap cluster analízis alapján:
```python
def generate_hypothetical_towers(clusters, towers_df):
    """
    A top gap klaszterek centroidjaiból generál hipotetikus LTE toronyokat.
    Sugár: DEFAULT_RADII_M['LTE'] = 300m (fix default, nem nearest-neighbor).
    """
    new_towers = []
    for i, cluster in enumerate(clusters[:5]):  # Top 5 gap régió
        new_towers.append({
            'lat':    cluster['lat'],
            'lon':    cluster['lon'],
            'radius': DEFAULT_RADII_M['LTE'],
            'radio':  'LTE',
            'label':  f"Hipotetikus #{i+1}"
        })
    return new_towers
```

**Opcionálisan kézi lista is megadható** `config.py`-ban:
```python
MANUAL_NEW_TOWERS = []  # Üres = automatikus. Vagy: [{'lat': 47.5, 'lon': 19.0, 'radius': 300}, ...]
```

### `simulate_new_towers(coverage, grid_lat, grid_lon, new_towers, original_stats) -> dict`

```python
def simulate_new_towers(coverage, grid_lat, grid_lon, new_towers, original_stats):
    # Új grid a meglévő másolata
    new_coverage = coverage.copy()
    
    # Minden új torony hozzáadása (ugyanaz az algoritmus mint rasterizer-ben)
    for tower in new_towers:
        _add_tower_to_grid(new_coverage, grid_lat, grid_lon,
                           tower['lat'], tower['lon'], tower['radius'])
    
    # Új statisztikák
    from src.gap_analyzer import analyze_gaps  # abszolút import – main.py-ból hívjuk
    new_stats = analyze_gaps(new_coverage, grid_lat, grid_lon)
    
    gap_delta = original_stats['gap_area_km2'] - new_stats['gap_area_km2']
    gap_pct   = gap_delta / original_stats['gap_area_km2'] * 100
    
    return {
        'before':              original_stats,
        'after':               new_stats,
        'new_towers':          new_towers,
        'gap_reduction_km2':   gap_delta,
        'gap_reduction_pct':   gap_pct,
        'original_grid':       coverage,        # ← az eredeti grid a diff-hez
        'new_coverage_grid':   new_coverage,
    }
```

### `_add_tower_to_grid(coverage, grid_lat, grid_lon, tlat, tlon, radius)`

**FONTOS: ezt a segédfüggvényt is definiálni kell `simulator.py`-ban** –
ugyanaz az algoritmus mint a rasterizer bounding-box logikája, de egyetlen toronyra:

```python
def _add_tower_to_grid(coverage, grid_lat, grid_lon, tlat, tlon, radius):
    """Egyetlen torony lefedettségét adja hozzá a coverage gridhez (in-place)."""
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
```

### `create_simulation_figure(sim_results, grid_lat, grid_lon, bbox) -> Figure`

**FONTOS: ez a függvény a `visualizer.py`-ban legyen** (nem simulator.py-ban),
mert az összes többi vizualizációs függvény ott van, és a main.py is onnan importálja.

**3 subplot (1 sor, 3 oszlop), figsize=(18, 6):**

1. **Előtte:** `sim_results['before']` coverage grid heatmap
2. **Utána:** `sim_results['new_coverage_grid']` heatmap + új tornyok csillag markerrel
3. **Különbség:** `sim_results['new_coverage_grid'] - sim_results['original_grid']`
   map zölddel ahol pozitív (új fedettség keletkezett)

**Fejléc szöveg:**
```
Gap csökkentés: {gap_reduction_km2:.2f} km² ({gap_reduction_pct:.1f}%)
Új tornyok: {len(new_towers)} db
```

---

## 11. MAIN.PY – ORCHESTRÁTOR

```python
#!/usr/bin/env python3
"""
Project 12: Mobile Tower Coverage Mapper
Belépési pont – az egész pipeline-t futtatja sorban.
"""
import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # GUI nélküli backend – szükséges szerver környezetben

from config import *
from src.data_loader import load_towers, clean_towers, save_processed
from src.signal_model import estimate_radii, add_shapely_geometries
from src.rasterizer import create_grid, rasterize_coverage
from src.gap_analyzer import analyze_gaps, find_gap_clusters, compute_gap_polygons
from src.visualizer import (create_folium_map, create_heatmap_figure,
                             create_gap_analysis_figure, create_simulation_figure)
from src.simulator import generate_hypothetical_towers, simulate_new_towers

def main():
    # --- Mappák létrehozása ---
    for d in ['data/raw', 'data/processed', 'output']:
        os.makedirs(d, exist_ok=True)

    print("=" * 55)
    print("  Project 12 – Mobile Tower Coverage Mapper")
    print("=" * 55)

    # --- 1. Adatbetöltés ---
    print("\n[1/6] Adatbetöltés...")
    towers = load_towers(RAW_DATA_PATH, BBOX, MCC)
    towers = clean_towers(towers)
    print(f"  ✓ {len(towers):,} torony betöltve {CITY} területéről")
    print(f"  Rádiótípusok: {towers['radio'].value_counts().to_dict()}")

    # --- 2. Sugár becslés ---
    print("\n[2/6] Lefedettségi sugarak becslése...")
    towers['radius'] = estimate_radii(towers)
    print(f"  ✓ Sugár: min={towers['radius'].min():.0f}m, "
          f"max={towers['radius'].max():.0f}m, "
          f"átlag={towers['radius'].mean():.0f}m")
    towers = add_shapely_geometries(towers)
    print(f"  ✓ Shapely geometriák létrehozva: {len(towers)} kör")
    save_processed(towers.drop(columns=['geometry', 'radius_deg']), PROCESSED_PATH)

    # --- 3. Raszterizálás ---
    print(f"\n[3/6] Raszterizálás ({GRID_RESOLUTION}×{GRID_RESOLUTION} grid)...")
    grid_lat, grid_lon = create_grid(BBOX, GRID_RESOLUTION)

    # Cache: ha a grid újabb mint a towers processed fájl, betöltjük
    grid_is_fresh = (
        os.path.exists(COVERAGE_GRID_PATH) and
        os.path.exists(PROCESSED_PATH) and
        os.path.getmtime(COVERAGE_GRID_PATH) >= os.path.getmtime(PROCESSED_PATH)
    )
    if grid_is_fresh:
        print("  → Cache találat, betöltés...")
        coverage = np.load(COVERAGE_GRID_PATH)
    else:
        coverage = rasterize_coverage(towers, grid_lat, grid_lon)
        np.save(COVERAGE_GRID_PATH, coverage)
    print(f"  ✓ Coverage grid kész. Max: {coverage.max()} torony/cella")

    # --- 4. Gap analízis ---
    print("\n[4/6] Gap analízis...")
    stats = analyze_gaps(coverage, grid_lat, grid_lon)
    clusters = find_gap_clusters(stats['gap_mask'], grid_lat, grid_lon, top_n=10)
    print(f"  ✓ Fedettség: {(1 - stats['gap_fraction']) * 100:.1f}%")
    print(f"  ✓ Gap terület: {stats['gap_area_km2']:.1f} km²")
    print(f"  ✓ Átfedő terület: {stats['overlap_area_km2']:.1f} km²")
    print(f"  ✓ Legnagyobb gap klaszterek: {len(clusters)} azonosítva")
    gap_poly = compute_gap_polygons(stats['gap_mask'], grid_lat, grid_lon)
    if gap_poly:
        print(f"  ✓ Gap MultiPolygon (shapely): {gap_poly.area * 1e10:.1f} km² (fokos)")

    # --- 5. Vizualizáció ---
    print("\n[5/6] Vizualizáció...")

    # Folium interaktív térkép
    fmap = create_folium_map(towers, coverage, grid_lat, grid_lon, stats)
    fmap.save(OUTPUT_MAP_HTML)
    print(f"  ✓ Interaktív térkép: {OUTPUT_MAP_HTML}")

    # Matplotlib heatmap
    fig = create_heatmap_figure(coverage, BBOX, stats, towers)
    fig.savefig(OUTPUT_HEATMAP_PNG, dpi=150, bbox_inches='tight')
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"  ✓ Heatmap ábra: {OUTPUT_HEATMAP_PNG}")

    # Gap analízis ábra
    fig2 = create_gap_analysis_figure(coverage, stats, clusters, grid_lat, grid_lon)
    fig2.savefig(OUTPUT_GAP_PNG, dpi=150, bbox_inches='tight')
    plt.close(fig2)
    print(f"  ✓ Gap analízis ábra: {OUTPUT_GAP_PNG}")

    # --- 6. Szimuláció ---
    print("\n[6/6] Új torony szimuláció...")
    new_towers = (MANUAL_NEW_TOWERS if MANUAL_NEW_TOWERS
                  else generate_hypothetical_towers(clusters, towers))
    print(f"  → {len(new_towers)} hipotetikus torony elhelyezése...")
    sim = simulate_new_towers(coverage, grid_lat, grid_lon, new_towers, stats)

    fig3 = create_simulation_figure(sim, grid_lat, grid_lon, BBOX)
    fig3.savefig(OUTPUT_SIM_PNG, dpi=150, bbox_inches='tight')
    plt.close(fig3)

    print(f"  ✓ Gap csökkentés: {sim['gap_reduction_km2']:.2f} km² "
          f"({sim['gap_reduction_pct']:.1f}%)")
    print(f"  ✓ Szimulációs ábra: {OUTPUT_SIM_PNG}")

    # --- Összefoglaló ---
    print("\n" + "=" * 55)
    print("  KÉSZ! Kimeneti fájlok:")
    print(f"    {OUTPUT_MAP_HTML}   ← böngészőben nyisd meg")
    print(f"    {OUTPUT_HEATMAP_PNG}")
    print(f"    {OUTPUT_GAP_PNG}")
    print(f"    {OUTPUT_SIM_PNG}")
    print("=" * 55)

if __name__ == '__main__':
    main()
```

---

## 12. EDGE CASE-EK ÉS HIBAKEZELÉS

### Adatbetöltési hibák
| Hiba | Kezelés |
|------|---------|
| Fájl nem létezik | `FileNotFoundError` hasznos üzenettel |
| Üres szűrt DataFrame | `ValueError` + ellenőrizd az MCC-t |
| Rosszul formázott CSV | pandas `on_bad_lines='skip'` |
| Nagyon nagy fájl (>500MB) | chunked olvasás (már tervezett) |

### Sugár becslési edge case-ek
| Eset | Kezelés |
|------|---------|
| `averageSignal = 0` | Kezelés: átugrás, default-ra esés |
| Extrém pozitív dBm | Clip MIN_RADIUS_M-re |
| `range = -1` (OpenCelliD invalid) | <= 0-t nem fogadjuk el |
| Ismeretlen radio típus | DEFAULT_RADII_M.get(radio, 500) |

### Raszterizálási edge case-ek
| Eset | Kezelés |
|------|---------|
| Torony a bbox határán | lat_lo/hi max/min clampelés (már tervezett) |
| Nagyon kis sugár (< 1 cellányi) | Legalább 1 cellát fed – a center cella |
| Overflow int16 (max 32767) | Ha coverage.max() > 100, ez nem fog gondot okozni |

---

## 13. IMPLEMENTÁCIÓS SORREND CLAUDE CODE SZÁMÁRA

Ebben a sorrendben implementáld a modulokat:

```
1. requirements.txt  →  config.py
2. src/__init__.py   →  src/data_loader.py   (teszteld külön)
3. src/signal_model.py                        (teszteld külön)
4. src/rasterizer.py                          (teszteld külön, kis gridn)
5. src/gap_analyzer.py
6. src/visualizer.py
7. src/simulator.py
8. main.py                                    (integráció)
```

**Tesztelési módszer minden modulhoz:**
Minden modul végére írj egy `if __name__ == '__main__':` blokkot minimális
smoke-testtel, ami szintetikus adattal fut (nem kell a valódi CSV).

Példa `rasterizer.py` tesztje:
```python
if __name__ == '__main__':
    import numpy as np
    from config import BBOX, GRID_RESOLUTION
    
    # Szintetikus tornyok
    test_towers = pd.DataFrame({
        'lat': [47.5, 47.52, 47.48],
        'lon': [19.0, 19.05, 18.95],
        'radius': [500.0, 300.0, 800.0],
    })
    
    grid_lat, grid_lon = create_grid(BBOX, 100)  # kis grid a teszthez
    cov = rasterize_coverage(test_towers, grid_lat, grid_lon)
    print(f"Coverage max: {cov.max()}, gap fraction: {(cov==0).mean():.2%}")
    assert cov.max() >= 1, "Legalább egy cellát be kell fedni!"
    print("OK")
```

---

## 14. SHAPELY HASZNÁLATA – KÖTELEZŐ

A feladat leírása explicit módon megköveteli a `shapely` könyvtár használatát.
A puszta numpy-os megközelítés nem elég – a shapely körök az adatmodell szerves részei kell legyenek.

### Hol kell shapely-t használni

**`src/signal_model.py` végén** – minden toronyhoz hozzunk létre egy Shapely `Point` objektumot
és buffereljük a becsült sugárral (fokokban, nem méterben!):

```python
from shapely.geometry import Point

def add_shapely_geometries(df: pd.DataFrame) -> pd.DataFrame:
    """
    Hozzáad egy 'geometry' oszlopot: shapely Point.buffer(radius_deg).
    A radius_deg a méteres sugár fokok-ba konvertálva a torony szélességénél.
    Ez a shapely-alapú reprezentáció párhuzamosan létezik a numpy-os raszterizálással.
    """
    R = EARTH_RADIUS_M
    # Sugár fokokban (lat irányban állandó, lon irányban szélességfüggő)
    df = df.copy()
    df['radius_deg'] = df['radius'] / (R * np.pi / 180)

    df['geometry'] = df.apply(
        lambda row: Point(row['lon'], row['lat']).buffer(row['radius_deg']),
        axis=1
    )
    return df
```

**`src/gap_analyzer.py`-ban** – a gap területek shapely MultiPolygon-ként is kiszámolhatók
(opcionális, de demonstrálja a shapely integrációt):

```python
from shapely.ops import unary_union
from shapely.geometry import box

def compute_gap_polygons(gap_mask, grid_lat, grid_lon) -> 'shapely.geometry.MultiPolygon':
    """
    A gap cellákat shapely box poligonokká alakítja, majd uniójukat veszi.
    Visszatér: egyetlen MultiPolygon a teljes gap területre.
    Felhasználás: területszámítás verifikálása, exportálás GeoJSON-be.
    """
    H, W = gap_mask.shape
    dlat = (grid_lat[-1, 0] - grid_lat[0, 0]) / (H - 1)
    dlon = (grid_lon[0, -1] - grid_lon[0, 0]) / (W - 1)

    boxes = []
    # Minden 3. gap cellát veszünk (teljesítmény) – demonstrációs célra elég
    for i in range(0, H, 3):
        for j in range(0, W, 3):
            if gap_mask[i, j]:
                lat = grid_lat[i, j]
                lon = grid_lon[i, j]
                boxes.append(box(lon - dlon/2, lat - dlat/2,
                                 lon + dlon/2, lat + dlat/2))
    if not boxes:
        return None
    return unary_union(boxes)
```

**`main.py`-ban** – hívjuk meg és logoljuk az eredményt:
```python
# A signal_model után:
towers = add_shapely_geometries(towers)
print(f"  ✓ Shapely geometriák létrehozva: {len(towers)} kör")

# Gap analízis után:
gap_poly = compute_gap_polygons(stats['gap_mask'], grid_lat, grid_lon)
if gap_poly:
    print(f"  ✓ Gap MultiPolygon area (shapely): {gap_poly.area * 1e10:.1f} km² (fokos)")
```

---

## 15. NOTES – AMIT CLAUDE CODE-NAK TUDNIA KELL

1. **`matplotlib.use('Agg')`** kell a `main.py` elején, mielőtt bármi mást importálsz
   a matplotlib-ből. Headless (GUI nélküli) módban fut.

2. **Koordináta sorrend:** numpy `meshgrid(..., indexing='ij')` esetén
   `coverage[i, j]` ahol `i` a lat index (sor), `j` a lon index (oszlop).
   Az `imshow`-nál `origin='lower'` kell hogy a déli rész lent legyen.

3. **Folium verzió:** A `folium.plugins.HeatMap` a `folium.plugins`-ban van,
   nem a főmodulban. Import: `from folium.plugins import HeatMap`

4. **tqdm import:** `from tqdm import tqdm` a rasterizer-ben a progress bar-hoz.

5. **A `range` Python kulcsszó konfliktus:** Mindig `df['range']`-ként hivatkozz rá.

6. **Memória:** 500×500 int16 array = 500KB. A towers DataFrame 10000 toronnyal ~5MB.
   A processing során párhuzamosan ne tarts több grid másolatot memóriában.

7. **averageSignal előjele:** Az OpenCelliD-ben a jelszint mindig negatív dBm (pl. -85).
   A path loss képlet ezt feltételezi. Ha véletlenül pozitív érték kerül be, a clip kezeli.

8. **shapely geometry oszlop mentése:** A `towers` DataFrame geometry oszlopa nem
   serializálható sima CSV-be. Ezért `save_processed` előtt drop-oljuk:
   `.drop(columns=['geometry', 'radius_deg'])` – ez már bele van írva a main.py-ba.

---

*Plan verzió: 1.0 – Teljes specifikáció Claude Code implementáláshoz.*
