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
MAX_RADIUS_M = 1000       # max elfogadott sugár méterben – urbánus korlát Budapesthez
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
OUTPUT_GAP_HTML    = 'output/gap_analysis.html'
OUTPUT_SIM_PNG     = 'output/simulation_report.png'
OUTPUT_SIM_HTML    = 'output/simulation_report.html'

# Szimuláció – kézi toronyhelyek a feladat-kiírás szerint:
# "given a list of hypothetical new tower locations, compute how much the gap area would decrease"
# Üres lista = automatikus generálás a top gap-klaszterekből (simulator.generate_hypothetical_towers).
# Az alábbi 10 toronyhely a gap_analysis.png alapján kiválasztva, 1500 m LTE sugár
# (vidéki agglomerációban realisztikus érték).
MANUAL_NEW_TOWERS = [
    # Nagy peremvárosi gap-területek
    {'lat': 47.540, 'lon': 18.880, 'radius': 1500, 'radio': 'LTE'},  # #1  Budakeszi / nyugati hegyvidék
    {'lat': 47.620, 'lon': 19.000, 'radius': 1500, 'radio': 'LTE'},  # #2  Budakalász / Pomáz
    {'lat': 47.625, 'lon': 19.250, 'radius': 1500, 'radio': 'LTE'},  # #3  Fót / Mogyoród
    {'lat': 47.400, 'lon': 19.200, 'radius': 1500, 'radio': 'LTE'},  # #4  Vecsés
    {'lat': 47.360, 'lon': 19.300, 'radius': 1500, 'radio': 'LTE'},  # #5  Üllő / Gyál
    # Kiegészítő helyek belső / agglomerációs gap-foltokra
    {'lat': 47.555, 'lon': 18.930, 'radius': 1500, 'radio': 'LTE'},  # #6  Pesthidegkút / Hűvösvölgy
    {'lat': 47.430, 'lon': 19.080, 'radius': 1500, 'radio': 'LTE'},  # #7  Csepel-sziget északi rész
    {'lat': 47.510, 'lon': 19.220, 'radius': 1500, 'radio': 'LTE'},  # #8  Mátyásföld / Cinkota
    {'lat': 47.560, 'lon': 19.300, 'radius': 1500, 'radio': 'LTE'},  # #9  Kerepes / Kistarcsa
    {'lat': 47.450, 'lon': 18.890, 'radius': 1500, 'radio': 'LTE'},  # #10 Törökbálint / Diósd nyugat
]
