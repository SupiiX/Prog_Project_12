import os
import pandas as pd


KNOWN_RADIOS = {'GSM', 'UMTS', 'LTE', 'NR'}

# OpenCelliD CSV formátum: fejléc nélküli, az oszlopok fix sorrendben
OPENCELLID_COLUMNS = [
    'radio', 'mcc', 'net', 'area', 'cell', 'unit',
    'lon', 'lat', 'range', 'samples', 'changeable',
    'created', 'updated', 'averageSignal',
]
# Csak ezeket tartjuk meg
KEEP_COLS = ['radio', 'mcc', 'lon', 'lat', 'range', 'averageSignal']
USECOLS_IDX = [OPENCELLID_COLUMNS.index(c) for c in KEEP_COLS]


def load_towers(filepath: str, bbox: dict, mcc: int) -> pd.DataFrame:
    if not os.path.exists(filepath):
        raise FileNotFoundError(
            f"Data file not found: {filepath}\n"
            f"Download the OpenCelliD database: https://opencellid.org/downloads.php\n"
            f"Select the Hungary (MCC=216) CSV export and save it to: {filepath}"
        )

    chunks = []
    for chunk in pd.read_csv(
        filepath,
        header=None,
        names=OPENCELLID_COLUMNS,
        usecols=KEEP_COLS,
        chunksize=100_000,
        on_bad_lines='skip',
        low_memory=False,
    ):
        chunk = chunk[chunk['mcc'] == mcc]
        chunk = chunk[
            (chunk['lat'] >= bbox['lat_min']) & (chunk['lat'] <= bbox['lat_max']) &
            (chunk['lon'] >= bbox['lon_min']) & (chunk['lon'] <= bbox['lon_max'])
        ]
        if not chunk.empty:
            chunks.append(chunk)

    if not chunks:
        raise ValueError(
            f"No towers found in the specified area. "
            f"Check the MCC value ({mcc}) and the bounding box ({bbox})."
        )

    return pd.concat(chunks, ignore_index=True)


def clean_towers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=['lat', 'lon'])
    df = df[(df['lat'] > -90) & (df['lat'] < 90) &
            (df['lon'] > -180) & (df['lon'] < 180)]

    df = df.copy()
    df.loc[~df['radio'].isin(KNOWN_RADIOS), 'radio'] = 'LTE'

    df['range'] = pd.to_numeric(df['range'], errors='coerce').fillna(0)
    df.loc[df['range'] <= 0, 'range'] = 0

    df['averageSignal'] = pd.to_numeric(df['averageSignal'], errors='coerce').fillna(0)

    df = df.drop_duplicates(subset=['lat', 'lon', 'radio'])
    df = df.reset_index(drop=True)
    return df


def save_processed(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from config import BBOX, MCC, RAW_DATA_PATH

    print("Smoke test: data_loader")
    try:
        towers = load_towers(RAW_DATA_PATH, BBOX, MCC)
        towers = clean_towers(towers)
        print(f"  Loaded: {len(towers):,} towers")
        print(f"  Columns: {list(towers.columns)}")
        print(f"  Radio types: {towers['radio'].value_counts().to_dict()}")
        print("OK")
    except FileNotFoundError as e:
        print(f"  Data not available (expected): {e}")
        print("OK (no data)")
