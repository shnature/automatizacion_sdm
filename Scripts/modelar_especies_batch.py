"""
modelar_especies_batch.py
=========================
PASO B: modelación de distribución potencial por lotes (un modelo por especie).

Diseño de áreas:
  - M (calibración): unión nacional de subcuencas con presencias
    (Data/Areas_Modelacion/area_<especie>.geojson). Aquí se calcula el VIF y se
    entrena el modelo, para que el nicho completo de la especie quede representado.
  - G (proyección): cuenca del Biobío (BNA 083, proyeccion_cuenca_083.geojson).
  - Salida: predicción solo en G ∩ M. Las especies sin área en G se omiten.

Grilla canónica: EPSG:32719 (UTM 19S), píxel de 250 m (config TARGET_SCALE).

Pipeline por especie:
  1. Carga M y G; calcula G ∩ M. Si está vacío, la especie se omite.
  2. Predictores: mediana de GOOGLE/SATELLITE_EMBEDDING 2017-2024 (mosaico por
     año) + MapBiomas del año más reciente, reproyectados a 32719 / 250 m y
     recortados a M.
  3. VIF local: grilla gruesa de M descargada con geedim, 1500 celdas válidas,
     eliminación iterativa VIF >= 10.
  4. Grilla de entrenamiento (250 m, bandas seleccionadas) descargada con geedim
     y leída localmente con rasterio. Sobre ella:
       - Presencias: se asigna cada registro a su celda; una celda por presencia;
         thinning a ~1 km (un punto por bloque de 4x4 celdas).
       - Fondos: celdas válidas de M, sin repetición, excluyendo celdas de presencia.
       - Pseudo-ausencias: celdas de polígonos urbanos / relaves dentro de M,
         sin repetición, excluyendo presencias y fondos.
     Todas las observaciones son celdas distintas (sin conflictos).
  5. Entrenamiento en GEE (ee.Classifier.amnhMaxent, PROBABILITY) con los valores
     extraídos localmente (FeatureCollection de solo propiedades).
  6. Predicción recortada a G ∩ M y descarga a GeoTIFF con geedim (250 m, EPSG:32719).

Uso:
  .\\.venv\\Scripts\\python.exe .\\Scripts\\modelar_especies_batch.py --dry-run
  .\\.venv\\Scripts\\python.exe .\\Scripts\\modelar_especies_batch.py [--species ...] [--force]
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ee

import config_modelacion as cfg
import ee_utils_local as eel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("modelacion")

EPSG_CANONICO = int(cfg.CRS_CANONICO.split(":")[1])
_PSEUDO_UTM: dict[str, object] = {}


def _semilla(*partes: str) -> int:
    """Semilla determinista a partir de textos (reproducible entre corridas)."""
    return zlib.crc32("|".join(partes).encode()) % (2**31 - 1)


def _a_utm(geom_4326):
    """Geometría shapely en EPSG:4326 -> EPSG:32719."""
    import geopandas as gpd

    return gpd.GeoSeries([geom_4326], crs=4326).to_crs(cfg.CRS_CANONICO).iloc[0]


def _poligonos(geom) -> list:
    """Lista de polígonos simples de una geometría shapely."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if hasattr(geom, "geoms"):
        partes: list = []
        for g in geom.geoms:
            partes += _poligonos(g)
        return partes
    return []


def area_poligonal_limpia(geom_4326, min_km2: float):
    """Solo partes poligonales de `geom_4326` con área >= min_km2 (en UTM 19S).

    La intersección entre polígonos que comparten borde (M y G) produce
    GeometryCollections con líneas de área cero y polígonos residuales diminutos.
    Esta función descarta esos residuos. Devuelve un Polygon/MultiPolygon en
    EPSG:4326, o None si no queda ningún polígono válido.
    """
    import geopandas as gpd
    import shapely

    geom_utm = _a_utm(geom_4326)
    partes = [p for p in _poligonos(geom_utm) if p.area >= min_km2 * 1e6]
    if not partes:
        return None
    limpia = shapely.make_valid(shapely.union_all(partes))
    limpia = shapely.unary_union([p for p in _poligonos(limpia)])
    return gpd.GeoSeries([limpia], crs=cfg.CRS_CANONICO).to_crs(4326).iloc[0]


def _estimar_bloques(df: pd.DataFrame) -> int:
    """Número de bloques de thinning (1 km) ocupados. Estimación previa a GEE."""
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", cfg.CRS_CANONICO, always_xy=True)
    x, y = tr.transform(df["longitude"].to_numpy(), df["latitude"].to_numpy())
    bloques = pd.DataFrame({
        "bx": np.floor(np.asarray(x) / cfg.THINNING_METERS),
        "by": np.floor(np.asarray(y) / cfg.THINNING_METERS),
    }).drop_duplicates()
    return len(bloques)


# ---------------------------------------------------------------------------
# Plan de corridas
# ---------------------------------------------------------------------------

def construir_plan(solo_especies: list[str] | None) -> list[dict]:
    """Una corrida por especie: catálogo filtrado, presencias, áreas M y G ∩ M."""
    import geopandas as gpd

    catalogo = eel.aplicar_filtro_eib(eel.load_catalog())
    G = gpd.read_file(cfg.AREA_PROYECCION_GEOJSON).geometry.union_all()

    plan: list[dict] = []
    for _, fila in catalogo.sort_values("especie").iterrows():
        especie = fila["especie"]
        fid = cfg.species_id(especie)
        if solo_especies and especie not in solo_especies and fid not in solo_especies:
            continue
        path_m = cfg.AREAS_DIR / f"area_{fid}.geojson"
        if not path_m.exists():
            continue
        presencias = eel.load_presence(especie)
        if presencias is None:
            LOGGER.warning("Sin CSV de presencias: %s", especie)
            continue
        n = int(len(presencias))
        if n < cfg.MIN_RECORDS:
            LOGGER.info("%s: %d registros < MIN_RECORDS=%d; se omite.",
                        especie, n, cfg.MIN_RECORDS)
            continue
        bloques = _estimar_bloques(presencias)
        if bloques < cfg.MIN_CELDAS_PRESENCIA:
            LOGGER.info("%s: %d bloques de 1 km < MIN_CELDAS_PRESENCIA=%d; se omite.",
                        especie, bloques, cfg.MIN_CELDAS_PRESENCIA)
            continue
        existe = (cfg.MODELOS_DIR / fid / f"{fid}.tif").exists()
        M = gpd.read_file(path_m).geometry.union_all()
        area_m_km2 = float(_a_utm(M).area / 1e6)
        if not existe and area_m_km2 > cfg.AREA_MODELACION_MAX_KM2:
            LOGGER.info("%s: área M %.0f km² > AREA_MODELACION_MAX_KM2=%d; se omite.",
                        especie, area_m_km2, cfg.AREA_MODELACION_MAX_KM2)
            continue
        GM = area_poligonal_limpia(M.intersection(G), cfg.AREA_MIN_RESIDUO_KM2)
        if GM is None:
            LOGGER.info("%s: sin área poligonal en la cuenca %s; se omite.",
                        especie, cfg.CUENCA_PROYECCION_COD)
            continue
        plan.append({
            "especie": especie,
            "fid": fid,
            "criterios": fila["criterios"],
            "n_registros": n,
            "bloques_1km": bloques,
            "geom_m": M,
            "geom_gm": GM,
            "existe": existe,
        })
    return plan


def print_plan(plan: list[dict]) -> None:
    LOGGER.info("PLAN DE MODELACIÓN (%d corridas, 1 por especie):", len(plan))
    LOGGER.info("  grilla %s, píxel %d m | M = calibración, G&M = salida",
                cfg.CRS_CANONICO, cfg.TARGET_SCALE)
    for it in plan:
        area_gm = _a_utm(it["geom_gm"]).area / 1e6
        estado = " [ya existe]" if it["existe"] else ""
        LOGGER.info("  - %-30s %5d reg | ~%4d bloques 1 km | G&M %8.0f km2 | %s%s",
                    it["especie"], it["n_registros"], it["bloques_1km"],
                    area_gm, it["criterios"], estado)


# ---------------------------------------------------------------------------
# Bloques GEE
# ---------------------------------------------------------------------------

def preparar_predictores(area_ee):
    """Compuesto "actual": mediana de embeddings sobre mosaicos anuales y
    MapBiomas del año más reciente, en la grilla canónica (32719 / 250 m)."""
    import calendar

    anios = range(
        int(cfg.EMBEDDINGS_RANGO_MEDIA[0][:4]),
        int(cfg.EMBEDDINGS_RANGO_MEDIA[1][:4]) + 1,
    )
    mosaicos = []
    for anio in anios:
        m = (
            ee.ImageCollection(cfg.EMBEDDINGS_ID)
            .filterDate(f"{anio}-01-01", f"{anio}-12-31")
            .filterBounds(area_ee)
            .mosaic()
        )
        mosaicos.append(
            ee.Image(m.set("system:time_start", calendar.timegm((anio, 1, 1, 0, 0, 0))))
        )
    coleccion_anual = ee.ImageCollection.fromImages(mosaicos)
    n_imagenes = int(coleccion_anual.size().getInfo())
    if n_imagenes == 0:
        raise RuntimeError(
            f"Sin imágenes de embeddings en {cfg.EMBEDDINGS_RANGO_MEDIA} para el área."
        )
    LOGGER.info("    [predictores] mediana de %d mosaicos anuales (%s..%s)",
                n_imagenes, cfg.EMBEDDINGS_RANGO_MEDIA[0], cfg.EMBEDDINGS_RANGO_MEDIA[1])
    embeddings_mediana = coleccion_anual.median()

    land_use_img = ee.Image(cfg.MAPBIOMAS_ID)
    anios_uso = sorted(
        int(b.split("_")[-1])
        for b in land_use_img.bandNames().getInfo()
        if b.startswith("classification_")
    )
    anio_uso = max((a for a in anios_uso if a <= 2024), default=None)
    if anio_uso is None:
        LOGGER.info("    ! MapBiomas sin años recientes; usando %d.",
                    cfg.MAPBIOMAS_ANIO_FALLBACK)
        anio_uso = cfg.MAPBIOMAS_ANIO_FALLBACK
    else:
        LOGGER.info("    [predictores] MapBiomas classification_%d", anio_uso)

    predictors = embeddings_mediana.reproject(
        crs=cfg.CRS_CANONICO, scale=cfg.TARGET_SCALE
    )
    return predictors.addBands(
        land_use_img.select(f"classification_{anio_uso}")
        .reproject(crs=cfg.CRS_CANONICO, scale=cfg.TARGET_SCALE)
        .rename("uso_suelo")
    )


def vif_seleccion_bandas(predictors, area_ee, fid: str, cache_dir: Path,
                         area_km2: float) -> list[str]:
    """VIF sobre una grilla gruesa de M descargada localmente."""
    rng = np.random.default_rng(_semilla("vif", fid))
    bandas_todas = predictors.bandNames().getInfo()
    imagen = eel.imagen_con_mascara(predictors, bandas_todas, area_ee)

    if area_km2 > cfg.AREA_GRANDE_KM2:
        escalas = (cfg.VIF_GRID_METERS_GRANDE, cfg.VIF_GRID_METERS, cfg.TARGET_SCALE)
        LOGGER.info("    [VIF] área grande (%.0f km²): grilla inicial %d m",
                    area_km2, cfg.VIF_GRID_METERS_GRANDE)
    else:
        escalas = (cfg.VIF_GRID_METERS, cfg.TARGET_SCALE)

    df_num = pd.DataFrame()
    for escala in escalas:
        tif = cache_dir / f"{fid}_vif_{escala}m.tif"
        t_vif = time.time()
        eel.descargar_grilla(imagen, area_ee, escala,
                             bandas_todas + [eel.BANDA_MASCARA], tif)
        df_num = eel.muestra_celdas_validas(tif, bandas_todas, cfg.VIF_NUM_PIXELS, rng)
        tif.unlink(missing_ok=True)
        LOGGER.info("    [VIF] grilla %d m: %d celdas válidas (%.1f s)",
                    escala, len(df_num), time.time() - t_vif)
        if len(df_num) >= cfg.VIF_MIN_CELDAS:
            break
        LOGGER.warning("    [VIF] pocas celdas válidas a %d m; reintentando más fino.",
                       escala)
    if df_num.empty:
        raise RuntimeError("Sin celdas válidas para el muestreo VIF.")
    df_num = df_num.dropna(axis=1, how="all").dropna(axis=0, how="any")
    _, bandas = eel.filter_variables_by_vif(df_num, threshold=cfg.VIF_THRESHOLD)
    return bandas


def grilla_entrenamiento(predictors_filt, bandas, area_ee, cache_dir: Path, fid: str):
    """Descarga la grilla de entrenamiento (250 m, dentro de M) y la lee localmente.

    Devuelve (valores (B, H, W), valida (H, W), transform, crs).
    Verifica que la grilla esté en EPSG:32719 con píxeles de TARGET_SCALE.
    """
    tif = cache_dir / f"{fid}_train_{cfg.TARGET_SCALE}m.tif"
    t0 = time.time()
    eel.descargar_grilla(
        eel.imagen_con_mascara(predictors_filt, bandas, area_ee),
        area_ee, cfg.TARGET_SCALE, list(bandas) + [eel.BANDA_MASCARA], tif,
    )
    vals, valida, transform, crs = eel.leer_grilla(tif, len(bandas))
    _verificar_grilla(transform, crs, cfg.TARGET_SCALE, tif.name)
    LOGGER.info("    [grilla] %s: %dx%d celdas, %d válidas (%.1f s)",
                cfg.CRS_CANONICO, valida.shape[1], valida.shape[0],
                int(valida.sum()), time.time() - t0)
    return vals, valida, transform, crs


def _verificar_grilla(transform, crs, esperado_m: float, nombre: str) -> None:
    epsg = crs.to_epsg() if crs is not None else None
    if epsg != EPSG_CANONICO:
        raise RuntimeError(f"{nombre}: CRS {epsg}, se esperaba {EPSG_CANONICO}")
    if abs(transform.a - esperado_m) > 0.5 or abs(-transform.e - esperado_m) > 0.5:
        raise RuntimeError(
            f"{nombre}: píxel {transform.a:.2f} x {-transform.e:.2f} m, "
            f"se esperaba {esperado_m} m"
        )


# ---------------------------------------------------------------------------
# Selección de celdas de entrenamiento (local)
# ---------------------------------------------------------------------------

def celdas_presencia(df: pd.DataFrame, transform, valida: np.ndarray):
    """Registros -> celdas únicas válidas. Devuelve (filas, cols, n_fuera_de_M)."""
    filas, cols, dentro = eel.lonlat_a_celdas(
        transform, valida.shape, df["longitude"].to_numpy(), df["latitude"].to_numpy()
    )
    ok = np.zeros_like(dentro)
    ok[dentro] = valida[filas[dentro], cols[dentro]]
    n_fuera = int((~ok).sum())
    pares = np.unique(np.stack([filas[ok], cols[ok]], axis=1), axis=0)
    return pares[:, 0], pares[:, 1], n_fuera


def seleccionar_celdas(especie: str, fid: str, df: pd.DataFrame, transform,
                       valida: np.ndarray, M_utm, stats: dict):
    """Presencias (thinning), fondos y pseudo-ausencias como celdas distintas.

    Devuelve dict con índices (filas, cols) por clase: 'pres', 'fondo', 'pseudo'.
    """
    shape = valida.shape
    # Restricción explícita a M (no depender solo del recorte de la descarga).
    valida = valida & eel.mascara_poligonos([M_utm], transform, shape)
    pf, pc, n_fuera = celdas_presencia(df, transform, valida)
    stats["n_fuera_m"] = n_fuera
    stats["n_celdas_presencia"] = len(pf)

    # --- thinning espacial (~1 km) ---
    rng_thin = np.random.default_rng(_semilla("thin", fid))
    keep = eel.thinning_por_bloque(pf, pc, cfg.THINNING_BLOQUE_CELDAS, rng_thin)
    pf, pc = pf[keep], pc[keep]
    n_pres = len(pf)
    stats["n_tras_thinning"] = n_pres
    if n_pres < cfg.MIN_CELDAS_PRESENCIA:
        return None

    ocupado = np.zeros(shape, dtype=bool)
    ocupado[pf, pc] = True

    # --- fondos: celdas válidas de M, sin repetición, fuera de presencias ---
    rng_fondo = np.random.default_rng(_semilla("fondo", fid))
    cand_f, cand_c = np.nonzero(valida & ~ocupado)
    n_fondo = int(round(cfg.FONDO_RATIO * n_pres))
    if len(cand_f) < n_fondo:
        LOGGER.warning("    [fondo] solo %d celdas candidatas (se pidieron %d).",
                       len(cand_f), n_fondo)
        n_fondo = len(cand_f)
    sel = rng_fondo.choice(len(cand_f), size=n_fondo, replace=False)
    bf, bc = cand_f[sel], cand_c[sel]
    ocupado[bf, bc] = True
    stats["n_fondo"] = n_fondo

    # --- pseudo-ausencias: celdas dentro de polígonos urbanos / relaves ∩ M ---
    n_pseudo_obj = max(cfg.MIN_PSEUDO, int(cfg.PSEUDO_RATIO * n_pres))
    psf, psc = [], []
    for kind in ("urban", "relaves"):
        union = _union_pseudo_utm(kind)
        poligonos = _poligonos(union.intersection(M_utm))
        if not poligonos:
            LOGGER.info("    [pseudo] sin polígonos '%s' dentro de M.", kind)
            continue
        mask = eel.mascara_poligonos(poligonos, transform, shape) & valida & ~ocupado
        cf, cc = np.nonzero(mask)
        if len(cf) == 0:
            LOGGER.info("    [pseudo] '%s': sin celdas válidas fuera de presencias.", kind)
            continue
        rng_ps = np.random.default_rng(_semilla("pseudo", kind, fid))
        n = min(n_pseudo_obj, len(cf))
        s = rng_ps.choice(len(cf), size=n, replace=False)
        psf.append(cf[s])
        psc.append(cc[s])
        ocupado[cf[s], cc[s]] = True
        stats[f"n_pseudo_{kind}"] = n
    psf = np.concatenate(psf) if psf else np.array([], dtype=int)
    psc = np.concatenate(psc) if psc else np.array([], dtype=int)
    stats["n_pseudo"] = len(psf)

    # --- verificación: ninguna celda repetida entre clases ---
    todas = np.concatenate([
        np.ravel_multi_index((pf, pc), shape),
        np.ravel_multi_index((bf, bc), shape),
        np.ravel_multi_index((psf, psc), shape) if len(psf) else np.array([], dtype=int),
    ])
    stats["n_conflictos"] = int(len(todas) - len(np.unique(todas)))
    return {"pres": (pf, pc), "fondo": (bf, bc), "pseudo": (psf, psc)}


def _union_pseudo_utm(kind: str):
    if kind not in _PSEUDO_UTM:
        gdf = eel.load_pseudoausencias(kind).to_crs(cfg.CRS_CANONICO)
        _PSEUDO_UTM[kind] = gdf.geometry.union_all()
    return _PSEUDO_UTM[kind]


def features_desde_celdas(vals: np.ndarray, bandas: list[str], celdas: dict) -> ee.FeatureCollection:
    """FeatureCollection de solo propiedades: bandas + presence (1 presencia, 0 fondo/pseudo)."""
    filas, cols, y = [], [], []
    for clave, etiqueta in (("pres", 1), ("fondo", 0), ("pseudo", 0)):
        f, c = celdas[clave]
        filas.append(f)
        cols.append(c)
        y.append(np.full(len(f), etiqueta, dtype=float))
    F = np.concatenate(filas)
    C = np.concatenate(cols)
    X = vals[:, F, C].T.astype(np.float64)
    df = pd.DataFrame(X, columns=list(bandas))
    df["presence"] = np.concatenate(y)
    registros = [{k: float(v) for k, v in r.items()} for r in df.to_dict("records")]
    return ee.FeatureCollection([ee.Feature(None, r) for r in registros])


def descargar_geotiff(image, region_ee, out_tif: Path) -> None:
    """Descarga la predicción a GeoTIFF local (EPSG:32719, 250 m) con geedim."""
    import geedim  # noqa: F401  (registra el accessor .gd en ee.Image)

    exportable = image.gd.prepareForExport(
        crs=cfg.CRS_CANONICO,
        region=region_ee,
        scale=cfg.EXPORT_SCALE_METERS,
        bands=["probability"],
    )
    exportable.gd.toGeoTIFF(str(out_tif), overwrite=True)


# ---------------------------------------------------------------------------
# Ejecución por especie
# ---------------------------------------------------------------------------

def run_especie(item: dict, force: bool) -> tuple[str, dict]:
    """Corre el modelo de una especie. Devuelve (estado, estadísticas)."""
    especie, fid = item["especie"], item["fid"]

    out_dir = cfg.MODELOS_DIR / fid
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tif = out_dir / f"{fid}.tif"
    if out_tif.exists() and not force:
        LOGGER.info("    [SKIP] ya existe %s (use --force)", out_tif.name)
        return "skip", {}

    t0 = time.time()
    LOGGER.info(">>> %s | %d registros", especie, item["n_registros"])

    M_geom, GM_geom = item["geom_m"], item["geom_gm"]
    M_ee = eel.ee_geometry_from_shapely(M_geom)
    GM_ee = eel.ee_geometry_from_shapely(GM_geom)
    M_utm = _a_utm(M_geom)
    area_km2 = float(M_utm.area / 1e6)

    df_all = eel.load_presence(especie)
    if df_all is None or df_all.empty:
        raise RuntimeError("sin presencias")

    stats: dict = {
        "n_registros": len(df_all),
        "area_m_km2": round(area_km2, 1),
        "area_gm_km2": round(float(_a_utm(GM_geom).area / 1e6), 1),
    }
    cache_dir = cfg.PREDICTORES_CACHE_DIR / fid
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        predictors = preparar_predictores(M_ee)
        bandas = vif_seleccion_bandas(predictors, M_ee, fid, cache_dir, area_km2)
        predictors_filt = predictors.select(bandas)
        stats["n_bandas"] = len(bandas)

        vals, valida, transform, crs = grilla_entrenamiento(
            predictors_filt, bandas, M_ee, cache_dir, fid
        )
        stats["resolucion_m"] = float(transform.a)
        stats["crs_salida"] = cfg.CRS_CANONICO

        celdas = seleccionar_celdas(especie, fid, df_all, transform, valida, M_utm, stats)
        if celdas is None:
            LOGGER.warning("    [SKIP] %d celdas de presencia < MIN_CELDAS_PRESENCIA=%d",
                           stats["n_tras_thinning"], cfg.MIN_CELDAS_PRESENCIA)
            return f"skip (<{cfg.MIN_CELDAS_PRESENCIA} celdas)", stats
        LOGGER.info("    [celdas] presencias %d (de %d únicas, %d fuera de M) | fondo %d | pseudo %d | conflictos %d",
                    stats["n_tras_thinning"], stats["n_celdas_presencia"], stats["n_fuera_m"],
                    stats["n_fondo"], stats["n_pseudo"], stats["n_conflictos"])
        if stats["n_conflictos"] != 0:
            raise RuntimeError(f"{stats['n_conflictos']} celdas repetidas entre clases")

        training_features = features_desde_celdas(vals, bandas, celdas)
        final_classifier = ee.Classifier.amnhMaxent().setOutputMode("PROBABILITY")
        final_model = final_classifier.train(
            features=training_features,
            classProperty="presence",
            inputProperties=bandas,
        )
        suitability = (
            predictors_filt.clip(GM_ee)
            .classify(final_model, "probability")
            .select("probability")
        )
        descargar_geotiff(suitability, GM_ee, out_tif)

        # Verificación del raster exportado: CRS y tamaño de píxel.
        import rasterio
        with rasterio.open(out_tif) as ds:
            _verificar_grilla(ds.transform, ds.crs, cfg.EXPORT_SCALE_METERS, out_tif.name)
            stats["resolucion_salida_m"] = float(ds.res[0])
            stats["crs_salida"] = f"EPSG:{ds.crs.to_epsg()}"
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)

    stats["tiempo_s"] = round(time.time() - t0, 1)
    LOGGER.info("    OK %s (%.1f s)", out_tif.name, stats["tiempo_s"])
    return "ok", stats


COLUMNAS_LOG = [
    "timestamp", "especie", "criterios", "estado", "n_registros", "area_m_km2",
    "area_gm_km2", "n_fuera_m", "n_celdas_presencia", "n_tras_thinning", "n_fondo", "n_pseudo",
    "n_conflictos", "n_bandas", "resolucion_salida_m", "crs_salida", "tiempo_s",
]


def loguear_resultado(item: dict, estado: str, stats: dict) -> None:
    """Una fila por corrida en Resultados/log_modelacion.csv (reanudable/auditable)."""
    fila = {c: None for c in COLUMNAS_LOG}
    fila.update(stats)
    fila.update({
        "timestamp": pd.Timestamp.now().isoformat(timespec="seconds"),
        "especie": item["especie"],
        "criterios": item["criterios"],
        "estado": estado,
        "n_registros": item["n_registros"],
    })
    cfg.LOG_MODELACION_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([fila], columns=COLUMNAS_LOG).to_csv(
        cfg.LOG_MODELACION_CSV, mode="a",
        header=not cfg.LOG_MODELACION_CSV.exists(), index=False,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Modelación por lotes (M calibración, G∩M salida; 250 m, EPSG:32719)."
    )
    parser.add_argument("--species", nargs="*", default=None,
                        help="Nombres científicos o ids del catálogo")
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra el plan y sale (sin GEE).")
    parser.add_argument("--force", action="store_true",
                        help="Regenerar aunque el raster exista.")
    args = parser.parse_args()

    plan = construir_plan(args.species)
    if not plan:
        LOGGER.error("Plan vacío. Ejecuta primero generar_areas_modelacion.py.")
        return
    print_plan(plan)
    if args.dry_run:
        return

    eel.init_earthengine()

    n_ok = n_skip = n_fail = 0
    for item in plan:
        estado, stats = "error", {}
        try:
            estado, stats = run_especie(item, force=args.force)
        except Exception as e:  # noqa: BLE001
            LOGGER.exception("ERROR en %s: %s", item["especie"], e)
            estado = f"error ({e})"[:120]
            n_fail += 1
        if estado == "ok":
            n_ok += 1
        elif estado.startswith("skip"):
            n_skip += 1
        loguear_resultado(item, estado, stats)

    LOGGER.info("=" * 60)
    LOGGER.info("PROCESAMIENTO COMPLETADO. ok=%d skip=%d fail=%d", n_ok, n_skip, n_fail)
    LOGGER.info("Log: %s", cfg.LOG_MODELACION_CSV)


if __name__ == "__main__":
    main()
