"""
generar_areas_modelacion.py
===========================
PASO A: genera automáticamente el área de modelación de cada especie EIB.

Para cada especie (de los 4 catálogos):
1. Carga TODAS sus presencias (todos los años) desde Data/Presencias.
2. Selecciona las subcuencas BNA (DGA) que contienen presencias
   (intersección directa de cada punto con una subcuenca).
3. Los puntos que caen fuera de TODAS las subcuencas (típico en especies
   marinas/costeras) se asignan a la subcuenca más cercana (fallback).
4. El área de modelación es la unión de las subcuencas seleccionadas.
5. Guarda un GeoJSON por especie + un GPKG consolidado + un resumen CSV.

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


def area_para_especie(
    especie: str,
    presencias: pd.DataFrame,
    subcuencas: gpd.GeoDataFrame,
) -> tuple[dict | None, "object"]:
    """Calcula el área de modelación de una especie.

    Devuelve (registro_resumen, geometría_union) o (None, None) si no es posible.
    """
    pts = presencias.dropna(subset=["latitude", "longitude"]).copy()
    if pts.empty:
        LOGGER.warning("%s: sin presencias válidas.", especie)
        return None, None

    gdf_pts = gpd.GeoDataFrame(
        pts,
        geometry=[Point(x, y) for x, y in zip(pts["longitude"], pts["latitude"])],
        crs="EPSG:4326",
    )

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
        return None, None

    # ------------------------------------------------------------------
    # 3. Subcuencas 'envueltas': huecos internos entre las seleccionadas
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
        "n_puntos": int(len(gdf_pts)),
        "puntos_inside": n_puntos_inside,
        "puntos_fallback": n_puntos_fallback,
        "dist_fallback_max_km": round(
            max(distancias_fallback) / 1000.0, 2
        ) if distancias_fallback else 0.0,
        "n_subcuencas_direct": n_subcuencas_direct,
        "n_subcuencas_envueltas": n_envueltas,
        "n_huecos_detectados": n_huecos,
        "n_subcuencas": len(idx_sel),
        "codigos_subcuencas": ",".join(sorted(set(ids_subc))),
        "cod_cuencas": ",".join(sorted(set(cuencas_subc))),
        "area_km2": area_km2,
        "nombres_subcuencas": ";".join(sorted(nombres_subc)),
    }
    return resumen, union_geom


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
    subcuencas = eel.load_subcuencas()
    LOGGER.info("Subcuencas: %d features.", len(subcuencas))

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

    for _, fila in catalogo.iterrows():
        especie = fila["especie"]
        criterios = fila["criterios"]
        fid = cfg.species_id(especie)

        presencias = eel.load_presence(especie)
        if presencias is None:
            sin_presencia.append(especie)
            continue

        LOGGER.info(">>> %s (%d presencias)", especie, len(presencias))
        resumen, union_geom = area_para_especie(especie, presencias, subcuencas)
        if resumen is None:
            continue
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
            "    %d subcuencas (%d directas, %d envueltas) | fallback: %d pts | área %.1f km²",
            resumen["n_subcuencas"], resumen["n_subcuencas_direct"],
            resumen["n_subcuencas_envueltas"], resumen["puntos_fallback"],
            resumen["area_km2"],
        )

    resumen_df = pd.DataFrame(resumenes)
    if not resumen_df.empty:
        resumen_df.to_csv(cfg.RESUMEN_AREAS_CSV, index=False)
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
    LOGGER.info("ÁREAS GENERADAS: %d | sin CSV de presencias: %d",
                len(resumenes), len(sin_presencia))
    for s in sin_presencia:
        LOGGER.info("  - sin presencias: %s", s)
    LOGGER.info("=" * 60)


if __name__ == "__main__":
    main()
