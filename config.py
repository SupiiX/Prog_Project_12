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
OUTPUT_SIM_PNG     = 'output/simulation_report.png'

# Szimuláció – kézi toronyhelyek (üres = automatikus gap-klaszter alapú)
# Formátum: [{'lat': 47.50, 'lon': 19.05, 'radius': 300, 'radio': 'LTE'}, ...]
MANUAL_NEW_TOWERS = []
