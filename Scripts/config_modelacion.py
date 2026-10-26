"""
config_modelacion.py
====================
Parámetros centrales del proyecto de modelación de distribución de especies
(versión local). Todos los scripts importan sus rutas y constantes desde aquí.

Diseño de área (M / G):
  - M (calibración): unión de subcuencas con presencias. Aquí se
    muestrean presencias, fondos y pseudo-ausencias, y se calcula el VIF.
  - G (proyección): subcuencas de la cuenca indicada en CUENCA_PROYECCION_COD.
  - Salida: predicción solo en G ∩ M (fuera de M no hay calibración).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# RUTAS DEL PROYECTO
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT_DIR / "Data"

# Catálogos de especies (criterios EIB). DATOS FICTICIOS del ejemplo (Data/ejemplo/).
# Para usar tus propias especies, apunta estas rutas a tus catálogos.
CATALOGOS = {
    "amenazada": (DATA_DIR / "ejemplo" / "catalogos" / "catalogo_amenazadas.csv", ","),
    "singular": (DATA_DIR / "ejemplo" / "catalogos" / "catalogo_singulares.csv", ","),
}

# Carpetas con los CSV de presencia por especie (genero_especie.csv).
PRESENCIAS_DIRS = [
    DATA_DIR / "ejemplo" / "presencias",
]

# Shapefile de subcuencas para el cálculo de áreas de modelación.
# Ejemplo: cuadrícula FICTICIA. Para trabajo real, usa tu propio shapefile (p. ej., BNA-DGA).
SUBCUENCAS_SHP = DATA_DIR / "ejemplo" / "subcuencas" / "subcuencas_ficticias.shp"
SUBCUENCAS_CAMPOS = {
    "id": "COD_SUBC",     # ID de la subcuenca
    "nombre": "NOM_SUBC", # Nombre de la subcuenca
    "cuenca": "COD_CUEN", # Código de cuenca asociada
}
# CRS de referencia si el shapefile no trae .prj (el ejemplo sí lo trae, en EPSG:4326)
SUBCUENCAS_CRS = 4326

# Polígonos locales para pseudo-ausencias (ejemplo ficticio)
PSEUDOAUSENCIAS = {
    "urban": DATA_DIR / "ejemplo" / "pseudoausencias" / "areas_urbanas_ficticias.geojson",
    "relaves": DATA_DIR / "ejemplo" / "pseudoausencias" / "relaves_ficticios.geojson",
}

# Salidas del PASO A (áreas de modelación)
AREAS_DIR = DATA_DIR / "Areas_Modelacion"
AREAS_GPKG = AREAS_DIR / "areas_modelacion.gpkg"

# Cuenca de proyección G (código COD_CUEN del shapefile; 900 = cuenca FICTICIA del ejemplo)
CUENCA_PROYECCION_COD = "900"
AREA_PROYECCION_GEOJSON = AREAS_DIR / "proyeccion_ejemplo.geojson"
# Área mínima (km²) de un polígono residual de M ∩ G; menores se descartan
AREA_MIN_RESIDUO_KM2 = 1.0

# Salidas del PASO B (rasters y logs)
RESULTADOS_DIR = ROOT_DIR / "Resultados"
MODELOS_DIR = RESULTADOS_DIR / "Modelos_Distribucion"
RESUMEN_AREAS_CSV = RESULTADOS_DIR / "resumen_areas_modelacion.csv"
LOG_MODELACION_CSV = RESULTADOS_DIR / "log_modelacion.csv"

# ---------------------------------------------------------------------------
# FILTRO DE ESPECIES AMENAZADAS
# ---------------------------------------------------------------------------
# Solo se modelan especies amenazadas En Peligro (EN) o En Peligro Crítico (CR).
# Una especie también entra si está en otro criterio (singular, valor cultural,
# distribución restringida); en ese caso solo se quita el criterio "amenazada".
AMENAZADA_CATEGORIAS = ("EN", "CR")

# Excepciones explícitas por especie: {"Nombre científico": True/False}.
# Úsalas cuando la categoría `eecc` aplique solo a una región concreta.
# Vacío en el ejemplo (todas las especies ficticias usan su categoría directamente).
AMENAZADA_OVERRIDE: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# GOOGLE EARTH ENGINE
# ---------------------------------------------------------------------------
GEE_PROJECT = "TU_PROYECTO_GEE"  # Reemplazar por tu proyecto de Google Earth Engine
HIGH_VOLUME_ENDPOINT = "https://earthengine-highvolume.googleapis.com"

# Colecciones en GEE
EMBEDDINGS_ID = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"
# Rango temporal de la MEDIANA del modelo "actual" (un solo compuesto por especie)
EMBEDDINGS_RANGO_MEDIA = ("2017-01-01", "2024-12-31")
MAPBIOMAS_ID = (
    "projects/mapbiomas-chile/assets/LULC/COLLECTION-02/CLASSIFICATIONS/"
    "classification-final/clasificacion-final-2"
)
MAPBIOMAS_ANIO_FALLBACK = 2022

# ---------------------------------------------------------------------------
# GRILLA CANÓNICA
# ---------------------------------------------------------------------------
# Proyección métrica con píxeles cuadrados. Toda la deduplicación, el thinning,
# el muestreo de fondos y la exportación usan esta grilla.
CRS_CANONICO = "EPSG:32719"   # WGS 84 / UTM 19S
TARGET_SCALE = 250            # tamaño de píxel (m): predictores, entrenamiento y salida
PREDICTOR_SAMPLE_METERS = TARGET_SCALE
EXPORT_SCALE_METERS = TARGET_SCALE

# ---------------------------------------------------------------------------
# PARÁMETROS DE MODELACIÓN
# ---------------------------------------------------------------------------
MIN_RECORDS = 20              # mínimo de registros brutos para crear la corrida
MIN_CELDAS_PRESENCIA = 20     # mínimo de celdas de presencia tras deduplicar y thinning
# Área M máxima (km²) para lanzar una nueva corrida (control de cuota GEE).
# Las especies que ya tienen raster se conservan y no se regeneran salvo --force.
AREA_MODELACION_MAX_KM2 = 20000

VIF_THRESHOLD = 10            # umbral de Factor de Inflación de la Varianza
VIF_NUM_PIXELS = 1500         # celdas muestreadas para el cálculo del VIF
VIF_GRID_METERS = 500         # grilla gruesa del VIF (áreas normales)
VIF_GRID_METERS_GRANDE = 1000 # grilla del VIF para áreas grandes
AREA_GRANDE_KM2 = 50000       # umbral de área para usar VIF_GRID_METERS_GRANDE
VIF_MIN_CELDAS = 100          # mínimo de celdas válidas para un VIF estable

# Thinning espacial de presencias: un punto por bloque de THINNING_METERS
# (aprox., bloques alineados a la grilla de TARGET_SCALE)
THINNING_METERS = 1000
THINNING_BLOQUE_CELDAS = max(1, round(THINNING_METERS / TARGET_SCALE))

# Fondos: celdas válidas de M, sin repetición y fuera de celdas de presencia
FONDO_RATIO = 1.0             # n_fondo = FONDO_RATIO * n_presencias (tras thinning)

# Pseudo-ausencias (celdas de polígonos urbanos / relaves dentro de M)
PSEUDO_RATIO = 0.25           # n_pseudo = PSEUDO_RATIO * n_presencias
MIN_PSEUDO = 5                # mínimo por fuente

GEE_REINTENTOS = 3            # reintentos en descargas geedim
GEE_BACKOFF_S = 10            # backoff base (s) entre reintentos
PREDICTORES_CACHE_DIR = RESULTADOS_DIR / "_cache_predictores"  # TIFFs temporales

# ---------------------------------------------------------------------------
# ÁREAS DE MODELACIÓN: subcuencas "envueltas"
# ---------------------------------------------------------------------------
# Se rellenan los huecos internos de la unión de subcuencas con presencias y se
# incorpora toda subcuenca cuya área caiga >= TOLERANCIA_COBERTURA dentro de la
# geometría rellenada.
INCLUIR_SUBCUENCAS_ENVUELTAS = True
TOLERANCIA_COBERTURA = 0.99

# Máximo de vértices por polígono al exportar áreas (solo logging)
MAX_VERTICES_AREA = 500000


def species_id(name: str) -> str:
    """'Percilia irwini' -> 'percilia_irwini' (nombre corto para archivos)."""
    return name.strip().lower().replace(" ", "_")
