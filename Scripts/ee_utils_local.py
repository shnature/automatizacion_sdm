"""
ee_utils_local.py
=================
Utilidades para la versión local del pipeline de modelación (Google Earth Engine
sin Colab ni Drive):

- inicialización/autenticación de GEE,
- carga y filtrado de catálogos de especies (criterios EIB),
- resolución y normalización de CSV de presencias,
- geometrías locales (shapely/GeoJSON) a ee.Geometry,
- grillas descargadas con geedim y lectura local (rasterio),
- deduplicación por celda, thinning espacial y máscaras de polígonos,
- selección de variables por VIF,
- pseudo-ausencias locales (urbanos y relaves).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

import ee

import config_modelacion as cfg

LOGGER = logging.getLogger("modelacion")

# ---------------------------------------------------------------------------
# Google Earth Engine
# ---------------------------------------------------------------------------

def init_earthengine() -> None:
    """Inicializa EE con el proyecto del config; si no hay credenciales,
    lanza el flujo interactivo `ee.Authenticate()` (una sola vez por máquina)."""
    try:
        ee.Initialize(project=cfg.GEE_PROJECT, opt_url=cfg.HIGH_VOLUME_ENDPOINT)
    except Exception:
        LOGGER.info("Sin credenciales de GEE: iniciando autenticación interactiva...")
        ee.Authenticate(force=True)
        ee.Initialize(project=cfg.GEE_PROJECT, opt_url=cfg.HIGH_VOLUME_ENDPOINT)
    LOGGER.info(
        "GEE inicializado (proyecto=%s, endpoint high-volume).", cfg.GEE_PROJECT
    )


# ---------------------------------------------------------------------------
# Catálogos de especies y presencias
# ---------------------------------------------------------------------------

def load_catalog() -> pd.DataFrame:
    """Carga y consolida los 4 catálogos de especies EIB (sin filtrar).

    Columnas de salida: ['especie', 'criterios']
    - 'criterios': etiquetas unidas por ';' (amenazada;singular;...)
    """
    filas: list[dict] = []
    for criterio, (path, sep) in cfg.CATALOGOS.items():
        if not path.exists():
            LOGGER.warning("Catálogo no encontrado: %s", path)
            continue
        df = pd.read_csv(path, sep=sep)
        col_especie = next(col for col in df.columns if col.strip() == "Especie")
        for nombre in df[col_especie].dropna().astype(str):
            nombre = nombre.strip()
            if not nombre:
                continue
            existente = next((f for f in filas if f["especie"] == nombre), None)
            if existente is None:
                filas.append({"especie": nombre, "criterios": criterio})
            elif criterio not in existente["criterios"].split(";"):
                existente["criterios"] += ";" + criterio
    return pd.DataFrame(filas, columns=["especie", "criterios"])


# --- Filtro de amenazadas (solo EN / CR) ------------------------------------

_RE_CATEGORIA = re.compile(r"^\s*(CR|EN|VU|NT|LC|DD)\b")


def cargar_eecc() -> dict[str, str]:
    """Mapa especie -> texto de estado de conservación (columna `eecc`)."""
    path, sep = cfg.CATALOGOS["amenazada"]
    df = pd.read_csv(path, sep=sep)
    col_especie = next(col for col in df.columns if col.strip() == "Especie")
    return {
        str(nombre).strip(): str(eecc)
        for nombre, eecc in zip(df[col_especie], df["eecc"].fillna(""))
    }


def amenaza_relevante(especie: str, eecc: str) -> bool:
    """True si la especie tiene categoría EN o CR aplicable a Chile continental/Biobío.

    Reglas:
    - Excepción explícita en cfg.AMENAZADA_OVERRIDE (decisión documentada).
    - Segmento EN/CR sin paréntesis (aplica a todo Chile) -> True.
    - Solo EN/CR con paréntesis (restringido a región/isla) -> False, con aviso.
    """
    if especie in cfg.AMENAZADA_OVERRIDE:
        return cfg.AMENAZADA_OVERRIDE[especie]
    texto = " ".join(str(eecc).split())
    restringido = False
    for seg in texto.split(";"):
        m = _RE_CATEGORIA.match(seg)
        if not m or m.group(1) not in cfg.AMENAZADA_CATEGORIAS:
            continue
        if "(" in seg:
            restringido = True
            continue
        return True
    if restringido:
        LOGGER.warning(
            "%s: EN/CR solo con restricción regional (%s); revisar AMENAZADA_OVERRIDE.",
            especie, texto,
        )
    return False


def aplicar_filtro_eib(catalogo: pd.DataFrame) -> pd.DataFrame:
    """Quita el criterio 'amenazada' a las especies que no son EN/CR relevantes.

    Una especie se elimina del catálogo si no le queda ningún criterio.
    """
    eecc = cargar_eecc()
    filas: list[dict] = []
    quitadas: list[str] = []
    for _, fila in catalogo.iterrows():
        especie = fila["especie"]
        criterios = [c for c in str(fila["criterios"]).split(";") if c]
        if "amenazada" in criterios and not amenaza_relevante(
            especie, eecc.get(especie, "")
        ):
            criterios.remove("amenazada")
            quitadas.append(especie)
        if criterios:
            filas.append({"especie": especie, "criterios": ";".join(criterios)})
    LOGGER.info(
        "Filtro EIB: %d especies conservadas; criterio 'amenazada' quitado a %d especies (no EN/CR).",
        len(filas), len(quitadas),
    )
    return pd.DataFrame(filas, columns=["especie", "criterios"])


def find_presence_csv(especie: str) -> Optional[Path]:
    """Busca Data/Presencias/Presencias_modelacion/{amenazadas,no_amenazadas}/Genus_species.csv."""
    fid = cfg.species_id(especie)
    for d in cfg.PRESENCIAS_DIRS:
        path = d / f"{fid}.csv"
        if path.exists():
            return path
    return None


RENOMBRE_COLS = {"Anio": "year", "latitud": "latitude", "longitud": "longitude"}


def load_presence(especie: str) -> Optional[pd.DataFrame]:
    """Carga el CSV de presencias normalizado: year(int), latitude, longitude.

    Devuelve None si el archivo no existe.
    """
    path = find_presence_csv(especie)
    if path is None:
        return None
    df = pd.read_csv(path)
    df = df.rename(columns={c: RENOMBRE_COLS.get(c, c) for c in df.columns})
    faltantes = {"year", "latitude", "longitude"} - set(df.columns)
    if faltantes:
        raise ValueError(
            f"{especie}: columnas faltantes en {path.name}: {sorted(faltantes)}"
        )
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    for c in ("latitude", "longitude"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])
    df["year"] = df["year"].astype("Int64")
    df["especie"] = especie
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Geometrías
# ---------------------------------------------------------------------------

def ee_geometry_from_geojson_file(path: Path) -> "ee.Geometry":
    """Construye un ee.Geometry (Polygon/MultiPolygon) desde el GeoJSON del área."""
    with open(path, encoding="utf-8") as f:
        geojson = json.load(f)
    feats = geojson.get("features", [])
    if len(feats) != 1:
        raise ValueError(f"{path.name}: se esperaba 1 feature, hay {len(feats)}")
    raw = feats[0]["geometry"]
    if raw["type"] == "MultiPolygon":
        return ee.Geometry.MultiPolygon(raw["coordinates"], proj=None, geodesic=False)
    if raw["type"] == "Polygon":
        return ee.Geometry.Polygon(raw["coordinates"], proj=None, geodesic=False)
    raise ValueError(f"{path.name}: geometría no soportada: {raw['type']}")


def ee_geometry_from_shapely(geom) -> "ee.Geometry":
    """ee.Geometry (Polygon/MultiPolygon) a partir de una geometría shapely.

    Si recibe una GeometryCollection, conserva solo sus polígonos (descarta líneas
    y puntos residuales). Si no queda ningún polígono, lanza ValueError claro.
    """
    import shapely

    if geom.geom_type == "GeometryCollection":
        poligonos = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not poligonos:
            raise ValueError("GeometryCollection sin polígonos")
        geom = shapely.unary_union(poligonos)
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"geometría no soportada: {geom.geom_type}")
    return ee.Geometry(shapely.geometry.mapping(geom), opt_geodesic=False)


# ---------------------------------------------------------------------------
# Grillas (geedim computePixels) y lectura local
# ---------------------------------------------------------------------------

BANDA_MASCARA = "mascara_valida"


def imagen_con_mascara(image, bandas: Sequence[str], area_ee) -> "ee.Image":
    """Recorta `image` a `area_ee` y agrega la banda de validez (1 = dato, 0 = fuera/sin dato).

    El recorte al polígono (no solo a su bounding box) garantiza que ningún
    fondo, pseudo-ausencia ni predicción caiga fuera de M.
    """
    img = image.select(list(bandas)).clip(area_ee)
    mascara = img.select(bandas[0]).mask().rename(BANDA_MASCARA)
    return img.addBands(mascara)


def descargar_grilla(image, area_ee, scale: float, bandas: Sequence[str],
                     out_tif: Path) -> None:
    """Descarga `image` (bandas `bandas`) a GeoTIFF local en la grilla canónica.

    Reintenta con backoff ante errores transitorios de GEE. Sobrescribe `out_tif`.
    """
    import time

    import geedim  # noqa: F401  (registra el accessor .gd en ee.Image)

    out_tif = Path(out_tif)
    out_tif.parent.mkdir(parents=True, exist_ok=True)
    ultimo: Exception | None = None
    for intento in range(1, cfg.GEE_REINTENTOS + 1):
        try:
            exportable = image.gd.prepareForExport(
                crs=cfg.CRS_CANONICO,
                region=area_ee,
                scale=scale,
                dtype="float32",
                bands=list(bandas),
            )
            exportable.gd.toGeoTIFF(str(out_tif), overwrite=True)
            return
        except Exception as exc:  # noqa: BLE001 (reintento genérico)
            ultimo = exc
            LOGGER.warning(
                "  [grilla] %s: intento %d/%d falló (%s).",
                out_tif.name, intento, cfg.GEE_REINTENTOS, exc,
            )
            if intento < cfg.GEE_REINTENTOS:
                time.sleep(cfg.GEE_BACKOFF_S * intento)
    raise ultimo  # type: ignore[misc]


def leer_grilla(tif_path: Path, n_bandas: int):
    """Lee una grilla descargada.

    Devuelve (valores (n_bandas, H, W) float32, valida (H, W) bool, transform, crs).
    `valida` = máscara == 1 y todas las bandas finitas. La última banda del
    GeoTIFF es la máscara de validez.
    """
    import rasterio

    with rasterio.open(tif_path) as ds:
        data = ds.read()
        if data.dtype != np.float32:
            data = data.astype(np.float32)
        transform, crs = ds.transform, ds.crs
    if data.shape[0] != n_bandas + 1:
        raise ValueError(
            f"{Path(tif_path).name}: {data.shape[0]} bandas, se esperaban {n_bandas + 1}"
        )
    vals, mascara = data[:-1], data[-1]
    valida = (mascara == 1.0) & np.isfinite(vals).all(axis=0)
    return vals, valida, transform, crs


def muestra_celdas_validas(tif_path: Path, bandas: Sequence[str], n: int,
                           rng: np.random.Generator) -> pd.DataFrame:
    """Hasta `n` celdas válidas de una grilla (para el muestreo VIF)."""
    vals, valida, _, _ = leer_grilla(tif_path, len(bandas))
    filas, cols = np.nonzero(valida)
    if len(filas) == 0:
        return pd.DataFrame(columns=list(bandas))
    k = min(int(n), len(filas))
    sel = rng.choice(len(filas), size=k, replace=False)
    return pd.DataFrame(vals[:, filas[sel], cols[sel]].T.astype(np.float64),
                        columns=list(bandas))


def lonlat_a_celdas(transform, shape, lon, lat):
    """Coordenadas geográficas -> (fila, columna) de la grilla canónica.

    Devuelve (filas, cols, dentro): `dentro` es False para puntos fuera del raster.
    Requiere transform sin rotación (caso de los GeoTIFF de geedim).
    """
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", cfg.CRS_CANONICO, always_xy=True)
    x, y = tr.transform(np.asarray(lon, dtype=float), np.asarray(lat, dtype=float))
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    cols = np.where(ok, np.floor((x - transform.c) / transform.a), -1).astype(int)
    filas = np.where(ok, np.floor((y - transform.f) / transform.e), -1).astype(int)
    h, w = shape
    dentro = ok & (filas >= 0) & (filas < h) & (cols >= 0) & (cols < w)
    return filas, cols, dentro


def thinning_por_bloque(filas: np.ndarray, cols: np.ndarray, bloque: int,
                        rng: np.random.Generator) -> np.ndarray:
    """Conserva una celda aleatoria por bloque de `bloque` x `bloque` celdas.

    Devuelve los índices (ordenados) de las celdas conservadas.
    """
    idx = rng.permutation(len(filas))
    bloques = np.stack([filas[idx] // bloque, cols[idx] // bloque], axis=1)
    _, primera = np.unique(bloques, axis=0, return_index=True)
    return np.sort(idx[primera])


def mascara_poligonos(geoms: Sequence, transform, shape) -> np.ndarray:
    """Máscara booleana (H, W): True en celdas cuyo centro cae dentro de `geoms`."""
    from rasterio.features import geometry_mask

    if len(geoms) == 0:
        return np.zeros(shape, dtype=bool)
    return geometry_mask(list(geoms), out_shape=shape, transform=transform, invert=True)


# ---------------------------------------------------------------------------
# VIF (función idéntica al notebook)
# ---------------------------------------------------------------------------

def filter_variables_by_vif(dataframe: pd.DataFrame, threshold: float = 10.0):
    """Elimina iterativamente la variable con mayor VIF hasta quedar bajo umbral.

    Devuelve (dataframe_filtrado, lista_de_bandas_seleccionadas).
    """
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    from statsmodels.tools.sm_exceptions import SingularMatrixWarning

    import warnings
    warnings.simplefilter("ignore", SingularMatrixWarning)

    remaining_columns = dataframe.columns.tolist()

    while True:
        vif_data = dataframe[remaining_columns]
        vif_values = [
            variance_inflation_factor(vif_data.values, i)
            for i in range(vif_data.shape[1])
        ]
        max_vif_index = vif_values.index(max(vif_values))
        max_vif = max(vif_values)
        if max_vif < threshold:
            break
        LOGGER.info(
            "  [VIF] Eliminando '%s' con VIF %.2f",
            remaining_columns[max_vif_index], max_vif,
        )
        del remaining_columns[max_vif_index]

    filtered_data = dataframe[remaining_columns]
    bands = filtered_data.columns.tolist()
    LOGGER.info("  [VIF] Bandas seleccionadas: %s", bands)
    return filtered_data, bands


# ---------------------------------------------------------------------------
# Pseudo-ausencias y subcuencas (archivos locales)
# ---------------------------------------------------------------------------

_POLY_GEOCACHE: dict[str, "object"] = {}


def load_pseudoausencias(kind: str) -> "gpd.GeoDataFrame":
    """Carga (con caché) las geojsons de pseudo-ausencias en EPSG:4326."""
    import geopandas as gpd

    if kind in _POLY_GEOCACHE:
        return _POLY_GEOCACHE[kind]
    gdf = gpd.read_file(cfg.PSEUDOAUSENCIAS[kind])
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)
    _POLY_GEOCACHE[kind] = gdf
    return gdf


def load_subcuencas() -> "gpd.GeoDataFrame":
    """Carga el shape de subcuencas BNA (DGA) y lo reproyecta a EPSG:4326."""
    import geopandas as gpd

    gdf = gpd.read_file(cfg.SUBCUENCAS_SHP)
    if gdf.crs is None:
        gdf = gdf.set_crs(cfg.SUBCUENCAS_CRS)
    return gdf.to_crs(4326)
