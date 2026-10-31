"""Carrega data/vehicles.csv(.bz2) em um banco SQLite (data/vehicles.db).

Uso: python build_db.py [caminho_csv] [caminho_db]
Só usa a biblioteca padrão.
"""
import bz2
import csv
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "vehicles.csv.bz2")
DST = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "data", "vehicles.db")

SCHEMA = """
CREATE TABLE vehicles (
    vehicle_id            INTEGER PRIMARY KEY,
    vin                   TEXT NOT NULL,
    make                  TEXT NOT NULL,
    model                 TEXT NOT NULL,
    model_year            INTEGER,
    vehicle_type          TEXT,
    fuel_type             TEXT,
    engine_displacement_l REAL,
    cylinders             INTEGER,
    horsepower_hp         INTEGER,
    torque_lb_ft          REAL,
    transmission          TEXT,
    drivetrain            TEXT,
    weight_lb             INTEGER,
    length_in             REAL,
    doors                 INTEGER,
    mpg_city              REAL,
    mpg_highway           REAL,
    range_miles           INTEGER,
    price_usd             REAL,
    origin_country        TEXT,
    assembly_country      TEXT,
    exterior_color        TEXT,
    safety_rating_5       REAL
);
"""

INDEXES = [
    "CREATE UNIQUE INDEX idx_vin ON vehicles(vin)",
    "CREATE INDEX idx_make_model ON vehicles(make, model)",
    "CREATE INDEX idx_year ON vehicles(model_year)",
    "CREATE INDEX idx_type ON vehicles(vehicle_type)",
    "CREATE INDEX idx_fuel ON vehicles(fuel_type)",
    "CREATE INDEX idx_price ON vehicles(price_usd)",
    "CREATE INDEX idx_hp ON vehicles(horsepower_hp)",
    "CREATE INDEX idx_origin ON vehicles(origin_country)",
]

INT_COLS = {"vehicle_id", "model_year", "cylinders", "horsepower_hp", "weight_lb", "doors", "range_miles"}
REAL_COLS = {"engine_displacement_l", "torque_lb_ft", "length_in", "mpg_city", "mpg_highway",
             "price_usd", "safety_rating_5"}


def convert(col, value):
    if value == "":
        return None  # vazio no CSV vira NULL (ex.: mpg de carro elétrico)
    if col in INT_COLS:
        return int(float(value))
    if col in REAL_COLS:
        return float(value)
    return value


def main():
    if os.path.exists(DST):
        os.remove(DST)
    opener = bz2.open if SRC.endswith(".bz2") else open
    con = sqlite3.connect(DST)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
    con.executescript(SCHEMA)
    with opener(SRC, "rt", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        sql = f"INSERT INTO vehicles ({','.join(header)}) VALUES ({','.join('?' * len(header))})"
        batch, total = [], 0
        for row in reader:
            batch.append([convert(c, v) for c, v in zip(header, row)])
            if len(batch) >= 50_000:
                con.executemany(sql, batch)
                total += len(batch)
                batch.clear()
                print(f"  {total:,} linhas...", flush=True)
        if batch:
            con.executemany(sql, batch)
            total += len(batch)
    con.commit()
    print("Criando índices...", flush=True)
    for stmt in INDEXES:
        con.execute(stmt)
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"OK: {total:,} veículos -> {DST} ({os.path.getsize(DST) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
