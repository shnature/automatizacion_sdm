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
# ÁREAS DE MODELACIÓN: casco convexo de presencias
# ---------------------------------------------------------------------------
# Además de las subcuencas con presencias (directas o por fallback), se incluye
# TODAS las unidades de cuenca que intersectan el CASCO CONVEXO de las
# presencias de la especie. Así el área M cubre la distribución posible entre
# la presencia más austral y la más boreal sin quedar fragmentada en parches
# desalineados. Aplica a todas las especies (el casco de especies marinas se
# apoya en el mar y toma solo las unidades costeras que intersecta).
INCLUIR_CASCO_CONVEXO = True
CASCO_MIN_PRES = 3  # mínimo de presencias para calcular el casco

# ---------------------------------------------------------------------------
# ÁREAS DE MODELACIÓN: presencias outliers y Chile continental
# ---------------------------------------------------------------------------
# Outliers: presencencia AISLADA = distancia al k-ésimo vecino más cercano >
# OUTLIER_KNN_KM (en métrica UTM). Se descarta de todo el paso A, así que el
# casco no la engloba y el paso B la deja fuera vía n_fuera_m. El criterio es
# espacial (por aislamiento), no univariado: no corta colas legítimas de
# distribuciones bimodales o de amplio rango. Resultados/outliers_descartados.csv
# registra cada descarte con su distancia, para revisión caso a caso.
OUTLIER_FILTRO = True
OUTLIER_KNN_K = 3       # vecino de referencia
OUTLIER_KNN_KM = 100    # umbral de aislamiento (km)
OUTLIER_MIN_PRES = 10   # con menos presencias, no se filtra (casos muy chicos)
OUTLIERS_LOG_CSV = RESULTADOS_DIR / "outliers_descartados.csv"

# Chile continental: de la capa de subcuencas solo se conservan las unidades
# cuyo punto representativo queda dentro del rectángulo continental. En la
# capa BNA (DGA) este filtro deja fuera únicamente Isla de Pascua (lon -109.4)
# e Islas Juan Fernández (lon -78.8); si la capa incluye otras unidades
# oceánicas, este filtro también las dejaría fuera.
CONTINENTE_LON_MIN = -76.0
CONTINENTE_LAT_MIN = -56.6
CONTINENTE_LAT_MAX = -17.4

# ---------------------------------------------------------------------------
# ÁREAS DE MODELACIÓN: subcuencas "envueltas"
# ---------------------------------------------------------------------------
# Se rellenan los huecos internos de la unión de subcuencas con presencias y se
# incorpora toda subcuenca cuya área caiga >= TOLERANCIA_COBERTURA dentro de la
# geometría rellenada. (Complemento del casco convexo, para vacíos interiores
# que queden tras la selección.)
INCLUIR_SUBCUENCAS_ENVUELTAS = True
TOLERANCIA_COBERTURA = 0.99

# Máximo de vértices por polígono al exportar áreas (solo logging)
MAX_VERTICES_AREA = 500000


def species_id(name: str) -> str:
    """'Percilia irwini' -> 'percilia_irwini' (nombre corto para archivos)."""
    return name.strip().lower().replace(" ", "_")
