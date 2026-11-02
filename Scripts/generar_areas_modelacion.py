"""
generar_areas_modelacion.py
===========================
PASO A: genera automáticamente el área de modelación de cada especie EIB.

Para cada especie (de los catálogos configurados):
1. Carga TODAS sus presencias (todos los años) desde Data/Presencias.
2. Filtra presencias OUTLIERS: se descarta una presencencia aislada cuando su
   3er vecino más cercano queda a más de OUTLIER_KNN_KM (100 km por defecto).
   Especies con < OUTLIER_MIN_PRES presencias no se filtran. Cada descarte
   queda en Resultados/outliers_descartados.csv (auditoría).
3. Se cargan las subcuencas BNA (DGA) y se conservan solo las de Chile
   continental (queda fuera Isla de Pascua y Juan Fernández).
4. Selecciona las subcuencas que contienen presencias (intersección directa).
5. Los puntos que caen fuera de TODAS las subcuencas (típico en especies
   marinas/costeras) se asignan a la subcuenca más cercana (fallback).
6. CASCO CONVEXO: se calcula el casco
   convexo de las presencias (ya sin outliers) y se incorporan TODAS las
   subcuencas que intersectan el casco. Así el área M cubre la distribución
   posible de sur a norte sin quedar fragmentada. Con menos de
   CASCO_MIN_PRES presencias, se omite el casco.
7. Se rellenan los huecos internos residuales (subcuencas "envueltas").
8. El área de modelación es la unión de las subcuencas seleccionadas.
9. Guarda un GeoJSON por especie + un GPKG consolidado + un resumen CSV.

Ejecución:
    .\\.venv\\Scripts\\python.exe .\\Scripts\\generar_areas_modelacion.py
    (opcional) --species "Percilia irwini"  para una sola especie
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_modelacion as cfg
import ee_utils_local as eel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("areas")


def _utm_epsg_para(lon: float) -> int:
    """EPSG UTM 18S/19S según la longitud, para cálculos métricos."""
    return 32719 if lon >= -72.0 else 32718


def _subcuencas_continente(subcuencas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Deja solo las subcuencas de Chile CONTINENTAL.

    Descarta las features cuyo punto representativo queda fuera del
    rectángulo continental (config CONTINENTE_*). En la capa BNA este filtro
    deja fuera únicamente Isla de Pascua e Islas Juan Fernández.
    """
    rp = subcuencas.geometry.representative_point()
    dentro = pd.Series(
        (rp.x >= cfg.CONTINENTE_LON_MIN)
        & (rp.y >= cfg.CONTINENTE_LAT_MIN)
        & (rp.y <= cfg.CONTINENTE_LAT_MAX),
        index=subcuencas.index,
    )
    excluidas = subcuencas[~dentro]
    if not excluidas.empty:
        nombres = excluidas[cfg.SUBCUENCAS_CAMPOS["nombre"]].astype(str).unique().tolist()
        LOGGER.info(
            "Chile continental: %d subcuencas NO continentales excluidas (%s).",
            len(excluidas), "; ".join(nombres),
        )
    return subcuencas[dentro].copy()


def _filtrar_outliers(
    especie: str,
    gdf_pts: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, list[dict]]:
    """Descarta presencias AISLADAS (criterio kNN).

    Distancia al OUTLIER_KNN_K-ésimo vecino más cercano, en métrica UTM
    (zona de la especie). Punto con distancia > OUTLIER_KNN_KM sale de todo
    el paso A. El criterio es espacial, no univariado: no corta colas
    legítimas de distribuciones bimodales o de amplio rango.

    Devuelve (gdf_sin_outliers, filas_log) con cada descarte para el CSV de
    auditoría. Especies con < OUTLIER_MIN_PRES presencias no se filtran.
    """
    if not cfg.OUTLIER_FILTRO or len(gdf_pts) < cfg.OUTLIER_MIN_PRES:
        return gdf_pts, []

    from pyproj import Transformer
    from scipy.spatial import cKDTree

    lat = gdf_pts["latitude"].to_numpy(dtype=float)
    lon = gdf_pts["longitude"].to_numpy(dtype=float)
    tr = Transformer.from_crs(
        "EPSG:4326", f"EPSG:{_utm_epsg_para(float(np.median(lon)))}", always_xy=True
    )
    x, y = tr.transform(lon, lat)

    # k+1 incluye el propio punto (distancia 0), así que la fila k-ésima tras
    # descartarlo d2 es exactamente el k-ésimo vecino ajeno.
    k = min(cfg.OUTLIER_KNN_K + 1, len(gdf_pts))
    dist_vecinos, _ = cKDTree(np.c_[x, y]).query(np.c_[x, y], k=k)
    dist_k = np.atleast_2d(dist_vecinos)[:, -1]

    fuera = dist_k > cfg.OUTLIER_KNN_KM * 1000.0
    if not fuera.any():
        return gdf_pts, []

    filas: list[dict] = []
    anios = gdf_pts["Anio"] if "Anio" in gdf_pts.columns else gdf_pts.get("year")
    for pos in np.where(fuera)[0]:
        filas.append(
            {
                "especie": especie,
                "anio": None if anios is None else anios.iloc[pos],
                "latitud": round(float(lat[pos]), 6),
                "longitud": round(float(lon[pos]), 6),
                "dist_knn_km": round(float(dist_k[pos]) / 1000.0, 1),
            }
        )
    LOGGER.info(
        "    [outliers] %d presencias aisladas descartadas (kNN %d > %d km).",
        len(filas), cfg.OUTLIER_KNN_K, cfg.OUTLIER_KNN_KM,
    )
    return gdf_pts.iloc[~fuera].copy(), filas


def _rellenar_huecos(geom):
    """Rellena los huecos internos de un (Multi)Polygon.

    Para cada polígono simple reconstruye el polígono desde su anillo exterior
    (descarta la lista de agujeros). Muy útil para capturar las subcuencas
    'envueltas' por presencias (un aro de subcuencas con un vacío central).
    """
    import shapely

    if geom is None or geom.is_empty:
        return geom
    geom = shapely.make_valid(geom)

    if geom.geom_type == "Polygon":
        if len(geom.interiors) == 0:
            return geom
        return shapely.Polygon(geom.exterior)

    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        partes = []
        for g in geom.geoms:
            if g.geom_type == "Polygon":
                partes.append(shapely.Polygon(g.exterior))
        if not partes:
            return geom
        return shapely.make_valid(shapely.union_all(partes))

    return geom


def _indices_envueltas(
    subcuencas: gpd.GeoDataFrame,
    idx_sel: list[int],
) -> tuple[list[int], int]:
    """Subcuencas 'envueltas': dentro (>=TOLERANCIA_COBERTURA) de la unión
    rellenada con las ya seleccionadas.

    Devuelve (indices_envueltas, n_huecos_detectados).
    """
    import shapely

    seleccion = subcuencas.loc[subcuencas.index.isin(idx_sel)]
    union_rellena = _rellenar_huecos(seleccion.geometry.union_all())

    candidatos = subcuencas.loc[~subcuencas.index.isin(idx_sel)]
    if candidatos.empty or not cfg.INCLUIR_SUBCUENCAS_ENVUELTAS:
        return [], 0
    if candidatos.crs != subcuencas.crs:  # homogeneizar por si acaso
        candidatos = candidatos.to_crs(subcuencas.crs)

    envueltas: list[int] = []
    for idx, geom in candidatos.geometry.items():
        if geom is None or geom.is_empty:
            continue
        if not union_rellena.intersects(geom):
            continue
        inter = geom.intersection(union_rellena)
        ratio = inter.area / geom.area if geom.area > 0 else 0.0
        if ratio >= cfg.TOLERANCIA_COBERTURA:
            envueltas.append(idx)

    # conteo de huecos reales detectados (informativo)
    preliminar = shapely.make_valid(seleccion.geometry.union_all())
    if preliminar.geom_type == "Polygon":
        n_huecos = len(preliminar.interiors)
    elif preliminar.geom_type == "MultiPolygon":
        n_huecos = sum(len(p.interiors) for p in preliminar.geoms)
    else:
        n_huecos = 0
    return sorted(envueltas), n_huecos


# ---------------------------------------------------------------------------
# CASCO CONVEXO DE PRESENCIAS
# (equivale a st_convex_hull + selección de unidades que intersectan el casco,
# criterio validado antes con un prototipo en R)
# ---------------------------------------------------------------------------
def _subcuencas_casco(
    subcuencas: gpd.GeoDataFrame,
    gdf_pts: gpd.GeoDataFrame,
) -> tuple[list[int], float | None]:
    """Subcuencas que intersectan el casco convexo de las presencias.

    Criterio `st_convex_hull` + selección de todas las unidades de cuenca que
    intersectan el casco (equivalente a un prototipo previo en R). Con <
    CASCO_MIN_PRES presencias se omite el casco y solo cuentan las
    subcuencas con presencias.

    Devuelve (indices_nuevos, area_casco_km2) con indices_nuevos excluyendo
    los ya seleccionados por el caller. area_casco_km2 es None si el casco no
    es poligonal (puntos colineales) o el casco está desactivado.
    """
    import shapely

    if not cfg.INCLUIR_CASCO_CONVEXO or len(gdf_pts) < cfg.CASCO_MIN_PRES:
        if cfg.INCLUIR_CASCO_CONVEXO:
            LOGGER.info(
                "    [casco] %d presencias < %d: se omite el casco (selección directa).",
                len(gdf_pts), cfg.CASCO_MIN_PRES,
            )
        return [], None

    hull = gdf_pts.geometry.union_all().convex_hull

    area_casco: float | None = None
    if hull.geom_type == "Polygon":
        # Un casco no poligonal (puntos colineales) no tiene área.
        centro = hull.representative_point()
        area_casco = round(
            gpd.GeoSeries([hull], crs=4326).to_crs(_utm_epsg_para(centro.x)).area.iloc[0] / 1e6,
            1,
        )

    # Subcuencas que intersectan el casco (topología del casco, no del grafo
    # de adyacencia: robusta ante los huecos/salientes de la capa BNA).
    mask = shapely.intersects(hull, subcuencas.geometry.values)
    idx_casco = subcuencas.index[mask].tolist()
    return idx_casco, area_casco


def area_para_especie(
    especie: str,
    presencias: pd.DataFrame,
    subcuencas: gpd.GeoDataFrame,
) -> tuple[dict | None, "object", list[dict]]:
    """Calcula el área de modelación de una especie.

    Devuelve (registro_resumen, geometría_union, fichas_outliers) o
    (None, None, fichas_outliers) si no es posible.
    """
    pts = presencias.dropna(subset=["latitude", "longitude"]).copy()
    if pts.empty:
        LOGGER.warning("%s: sin presencias válidas.", especie)
        return None, None, None

    gdf_pts = gpd.GeoDataFrame(
        pts,
        geometry=[Point(x, y) for x, y in zip(pts["longitude"], pts["latitude"])],
        crs="EPSG:4326",
    )

    # ------------------------------------------------------------------
    # 0. Presencias outliers (aisladas) fuera del área de modelación
    # ------------------------------------------------------------------
    n_antes = len(gdf_pts)
    gdf_pts, outliers_log = _filtrar_outliers(especie, gdf_pts)
    n_outliers = n_antes - len(gdf_pts)

    # ------------------------------------------------------------------
    # 1. Puntos dentro de alguna subcuenca (intersección)
    # ------------------------------------------------------------------
    join = gpd.sjoin(gdf_pts, subcuencas, how="left", predicate="intersects")
    idx_sel = sorted(set(join["index_right"].dropna().unique().tolist()))
    n_subcuencas_direct = len(idx_sel)
    sinon = join[join["index_right"].isna()]
    n_puntos_fallback = int(sinon.index.nunique())
    n_puntos_inside = int(len(gdf_pts) - n_puntos_fallback)

    # ------------------------------------------------------------------
    # 2. Fallback: puntos fuera -> subcuenca más cercana (distancia métrica)
    # ------------------------------------------------------------------
    distancias_fallback: list[float] = []
    if n_puntos_fallback > 0:
        lon_ref = float(sinon["longitude"].median())
        epsg_m = _utm_epsg_para(lon_ref)
        sub_m = subcuencas.to_crs(epsg_m)
        gpts_m = gpd.GeoDataFrame(
            sinon[["longitude", "latitude"]].copy(),
            geometry=[
                Point(x, y)
                for x, y in zip(sinon["longitude"], sinon["latitude"])
            ],
            crs="EPSG:4326",
        ).to_crs(epsg_m)
        cerca = gpd.sjoin_nearest(gpts_m, sub_m, how="left", distance_col="dist_m")
        idx_otros = sorted(set(cerca["index_right"].dropna().unique().tolist()))
        idx_sel = sorted(set(idx_sel) | set(idx_otros))
        distancias_fallback = cerca["dist_m"].dropna().astype(float).tolist()

    if not idx_sel:
        LOGGER.error("%s: no se pudo asignar ninguna subcuenca.", especie)
        return None, None, outliers_log

    # ------------------------------------------------------------------
    # 3. CASCO CONVEXO de las presencias (sin outliers): subcuencas que
    #    intersectan el casco (intersección espacial, sin grafo de adyacencia).
    # ------------------------------------------------------------------
    idx_casco, area_casco = _subcuencas_casco(subcuencas, gdf_pts)
    n_casco = len(set(idx_casco) - set(idx_sel))
    if idx_casco:
        LOGGER.info(
            "    [casco] %d subcuencas nuevas | área del casco: %s km²",
            n_casco,
            f"{area_casco:,.1f}" if area_casco is not None else "n.d. (colineal)",
        )
        idx_sel = sorted(set(idx_sel) | set(idx_casco))

    # ------------------------------------------------------------------
    # 4. Subcuencas 'envueltas': huecos internos entre las seleccionadas
    # ------------------------------------------------------------------
    idx_env, n_huecos = _indices_envueltas(subcuencas, idx_sel)
    n_envueltas = len(set(idx_env) - set(idx_sel))
    if idx_env:
        LOGGER.info(
            "    [envueltas] %d subcuencas nuevas (%d huecos internos en la unión)",
            n_envueltas, n_huecos,
        )
        idx_sel = sorted(set(idx_sel) | set(idx_env))

    seleccion = subcuencas.loc[subcuencas.index.isin(idx_sel)]
    union_geom = seleccion.geometry.union_all()

    ids_subc = seleccion[cfg.SUBCUENCAS_CAMPOS["id"]].astype(str).tolist()
    nombres_subc = seleccion[cfg.SUBCUENCAS_CAMPOS["nombre"]].astype(str).unique().tolist()
    cuencas_subc = seleccion[cfg.SUBCUENCAS_CAMPOS["cuenca"]].astype(str).unique().tolist()

    # Área km² en un CRS métrico (zona UTM del centroide del área)
    centro = union_geom.representative_point()
    area_km2 = round(
        seleccion.to_crs(_utm_epsg_para(centro.x)).geometry.union_all().area / 1e6,
        1,
    )

    resumen = {
        "especie": especie,
        "n_puntos": int(n_antes),
        "n_outliers": int(n_outliers),
        "puntos_inside": n_puntos_inside,
        "puntos_fallback": n_puntos_fallback,
        "dist_fallback_max_km": round(
            max(distancias_fallback) / 1000.0, 2
        ) if distancias_fallback else 0.0,
        "n_subcuencas_direct": n_subcuencas_direct,
        "n_subcuencas_envueltas": n_envueltas,
        "n_subcuencas_casco": n_casco,
        "area_casco_km2": area_casco,
        "n_huecos_detectados": n_huecos,
        "n_subcuencas": len(idx_sel),
        "codigos_subcuencas": ",".join(sorted(set(ids_subc))),
        "cod_cuencas": ",".join(sorted(set(cuencas_subc))),
        "area_km2": area_km2,
        "nombres_subcuencas": ";".join(sorted(nombres_subc)),
    }
    return resumen, union_geom, outliers_log


def area_proyeccion(subcuencas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Área G: unión de las subcuencas de la cuenca de proyección (BNA 083)."""
    cod = subcuencas[cfg.SUBCUENCAS_CAMPOS["cuenca"]].astype(str).str.strip()
    sel = subcuencas.loc[cod == cfg.CUENCA_PROYECCION_COD]
    if sel.empty:
        raise ValueError(f"Sin subcuencas con COD_CUEN={cfg.CUENCA_PROYECCION_COD}")
    return gpd.GeoDataFrame(
        {
            "cuenca": [cfg.CUENCA_PROYECCION_COD],
            "n_subcuencas": [len(sel)],
        },
        geometry=[sel.geometry.union_all()],
        crs="EPSG:4326",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera áreas de modelación por especie (unión de subcuencas)."
    )
    parser.add_argument(
        "--species", nargs="*", default=None,
        help="Nombres científicos concretos (default: todas las del catálogo)",
    )
    args = parser.parse_args()

    LOGGER.info("Cargando catálogos de especies EIB...")
    catalogo = eel.aplicar_filtro_eib(eel.load_catalog())
    if args.species:
        catalogo = catalogo[catalogo["especie"].isin(args.species)]
    LOGGER.info("Especies en catálogo: %d", len(catalogo))

    LOGGER.info("Cargando subcuencas BNA (%s)...", cfg.SUBCUENCAS_SHP.name)
    subcuencas = _subcuencas_continente(eel.load_subcuencas())
    LOGGER.info("Subcuencas: %d features (Chile continental).", len(subcuencas))

    cfg.AREAS_DIR.mkdir(parents=True, exist_ok=True)
    cfg.RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    g = area_proyeccion(subcuencas)
    g.to_file(cfg.AREA_PROYECCION_GEOJSON, driver="GeoJSON")
    LOGGER.info(
        "Área de proyección G (cuenca %s, %d subcuencas): %s",
        cfg.CUENCA_PROYECCION_COD, int(g["n_subcuencas"].iloc[0]),
        cfg.AREA_PROYECCION_GEOJSON.name,
    )

    resumenes: list[dict] = []
    features_out: list[gpd.GeoDataFrame] = []
    sin_presencia: list[str] = []
    descartes_outliers: list[dict] = []

    for _, fila in catalogo.iterrows():
        especie = fila["especie"]
        criterios = fila["criterios"]
        fid = cfg.species_id(especie)

        presencias = eel.load_presence(especie)
        if presencias is None:
            sin_presencia.append(especie)
            continue

        LOGGER.info(">>> %s (%d presencias)", especie, len(presencias))
        resumen, union_geom, outliers_log = area_para_especie(especie, presencias, subcuencas)
        if resumen is None:
            continue
        descartes_outliers.extend(outliers_log)
        resumen["criterios"] = criterios

        gdf_area = gpd.GeoDataFrame(
            {
                "especie": [especie],
                "criterios": [criterios],
                "n_subcuencas": [resumen["n_subcuencas"]],
                "area_km2": [resumen["area_km2"]],
            },
            geometry=[union_geom],
            crs="EPSG:4326",
        )
        gdf_area.to_file(cfg.AREAS_DIR / f"area_{fid}.geojson", driver="GeoJSON")
        features_out.append(gdf_area)
        resumenes.append(resumen)

        LOGGER.info(
            "    %d subcuencas (%d directas, %d por casco, %d envueltas) | fallback: %d pts | área %.1f km²",
            resumen["n_subcuencas"], resumen["n_subcuencas_direct"],
            resumen["n_subcuencas_casco"],
            resumen["n_subcuencas_envueltas"], resumen["puntos_fallback"],
            resumen["area_km2"],
        )

    resumen_df = pd.DataFrame(resumenes)
    if not resumen_df.empty:
        resumen_df.to_csv(cfg.RESUMEN_AREAS_CSV, index=False)

        if descartes_outliers:
            df_out = pd.DataFrame(descartes_outliers)
            df_out.to_csv(cfg.OUTLIERS_LOG_CSV, index=False, encoding="utf-8-sig")
            LOGGER.info(
                "Presencias outliers descartadas: %d (auditoría: %s)",
                len(df_out), cfg.OUTLIERS_LOG_CSV.name,
            )

        gdf_all = gpd.GeoDataFrame(
            pd.concat(features_out, ignore_index=True), crs="EPSG:4326"
        )
        try:
            gdf_all.to_file(cfg.AREAS_GPKG, layer="areas", driver="GPKG")
            LOGGER.info("GPKG consolidado: %s", cfg.AREAS_GPKG)
        except Exception as e:  # tolerar GPKG bloqueado por QGIS
            LOGGER.error("No se pudo escribir %s (%s)", cfg.AREAS_GPKG, e)
    else:
        LOGGER.warning("No se generó ningún área.")

    LOGGER.info("=" * 60)
    LOGGER.info("ÁREAS GENERADAS: %d | sin CSV de presencias: %d | outliers descartados: %d",
                len(resumenes), len(sin_presencia), len(descartes_outliers))
    for s in sin_presencia:
        LOGGER.info("  - sin presencias: %s", s)
    LOGGER.info("=" * 60)


if __name__ == "__main__":
    main()
