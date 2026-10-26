"""
generar_datos_ficticios.py
==========================
Genera los datos FICTICIOS del ejemplo incluido en Data/ejemplo/.

Nada de lo que produce corresponde a observaciones, subcuencas ni polígonos reales:
  - subcuencas: una cuadrícula regular de 5 x 5 celdas (cuenca ficticia 900);
  - especies: nombres inventados y registros de presencia aleatorios (semilla fija);
  - catálogos y polígonos de pseudo-ausencias: construcciones simples.

Uso (desde la raíz del repositorio):
    python Scripts/generar_datos_ficticios.py
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLO = RAIZ / "Data" / "ejemplo"
SEMILLA = 2026

LON0, LON1 = -73.0, -72.0
LAT0, LAT1 = -37.5, -36.5
N_CELDAS = 5
TAMANO = (LON1 - LON0) / N_CELDAS

# Especies ficticias. "catalogo" indica en qué catálogo aparecen.
ESPECIES = [
    {"nombre": "Ficticia alpha", "centro": (-72.70, -37.30), "radio": 0.12, "n": 60,
     "catalogo": "amenazada", "eecc": "EN"},
    {"nombre": "Ficticia beta", "centro": (-72.30, -36.80), "radio": 0.12, "n": 50,
     "catalogo": "amenazada", "eecc": "CR"},
    # Solo VU: el filtro EN/CR le quita el criterio "amenazada" y no se modela.
    {"nombre": "Ficticia gamma", "centro": (-72.60, -36.70), "radio": 0.15, "n": 40,
     "catalogo": "amenazada", "eecc": "VU"},
    {"nombre": "Ejemplar delta", "centro": (-72.80, -37.00), "radio": 0.18, "n": 45,
     "catalogo": "singular"},
    # 12 registros: queda por debajo de MIN_RECORDS (20) y se omite.
    {"nombre": "Ejemplar epsilon", "centro": (-72.40, -37.20), "radio": 0.10, "n": 12,
     "catalogo": "singular"},
]


def cuadricula_subcuencas() -> gpd.GeoDataFrame:
    filas = []
    for i in range(N_CELDAS):
        for j in range(N_CELDAS):
            x0 = LON0 + j * TAMANO
            y0 = LAT0 + i * TAMANO
            idx = i * N_CELDAS + j + 1
            filas.append({
                "COD_SUBC": f"9{idx:03d}",
                "NOM_SUBC": f"Subcuenca ficticia {idx:02d}",
                "COD_CUEN": "900",
                "geometry": box(x0, y0, x0 + TAMANO, y0 + TAMANO),
            })
    return gpd.GeoDataFrame(filas, crs="EPSG:4326")


def puntos_en_circulo(rng, centro, radio, n) -> tuple[np.ndarray, np.ndarray]:
    angulo = rng.uniform(0, 2 * np.pi, n)
    r = radio * np.sqrt(rng.uniform(0, 1, n))
    lon = centro[0] + r * np.cos(angulo)
    lat = centro[1] + r * np.sin(angulo)
    return lon, lat


def presencias(rng) -> None:
    carpeta = EJEMPLO / "presencias"
    carpeta.mkdir(parents=True, exist_ok=True)
    for esp in ESPECIES:
        lon, lat = puntos_en_circulo(rng, esp["centro"], esp["radio"], esp["n"])
        df = pd.DataFrame({
            "Especie": esp["nombre"],
            "Anio": rng.integers(2015, 2025, esp["n"]),
            "latitud": np.round(lat, 5),
            "longitud": np.round(lon, 5),
            "Origen": "FICTICIO",
        })
        nombre = esp["nombre"].lower().replace(" ", "_")
        df.to_csv(carpeta / f"{nombre}.csv", index=False)


def catalogos() -> None:
    carpeta = EJEMPLO / "catalogos"
    carpeta.mkdir(parents=True, exist_ok=True)
    amenazadas = pd.DataFrame(
        [{"Especie": e["nombre"], "eecc": e["eecc"]}
         for e in ESPECIES if e["catalogo"] == "amenazada"]
    )
    singulares = pd.DataFrame(
        [{"Especie": e["nombre"]} for e in ESPECIES if e["catalogo"] == "singular"]
    )
    amenazadas.to_csv(carpeta / "catalogo_amenazadas.csv", index=False)
    singulares.to_csv(carpeta / "catalogo_singulares.csv", index=False)


def pseudoausencias() -> None:
    carpeta = EJEMPLO / "pseudoausencias"
    carpeta.mkdir(parents=True, exist_ok=True)
    urbanos = gpd.GeoDataFrame(
        {"nombre": ["urbano ficticio 1", "urbano ficticio 2"]},
        geometry=[box(-72.45, -37.05, -72.40, -37.00), box(-72.95, -36.60, -72.90, -36.55)],
        crs="EPSG:4326",
    )
    relaves = gpd.GeoDataFrame(
        {"nombre": ["relave ficticio 1"]},
        geometry=[box(-72.25, -37.45, -72.15, -37.40)],
        crs="EPSG:4326",
    )
    urbanos.to_file(carpeta / "areas_urbanas_ficticias.geojson", driver="GeoJSON")
    relaves.to_file(carpeta / "relaves_ficticios.geojson", driver="GeoJSON")


def subcuencas() -> None:
    carpeta = EJEMPLO / "subcuencas"
    carpeta.mkdir(parents=True, exist_ok=True)
    cuadricula_subcuencas().to_file(carpeta / "subcuencas_ficticias.shp")


def main() -> None:
    rng = np.random.default_rng(SEMILLA)
    subcuencas()
    presencias(rng)
    catalogos()
    pseudoausencias()
    print(f"Datos ficticios generados en {EJEMPLO}")


if __name__ == "__main__":
    main()
