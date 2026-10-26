# Automatización de modelación de distribución de especies por lotes

**Batch species distribution modelling automation** · Python · Google Earth Engine · MaxEnt

Idioma / Language: [Español](#español) · [English](#english)

> **Estado / Status:** la etapa de validación cuantitativa del modelo aún no está incluida; se añadirá posteriormente. / The quantitative model validation stage is not included yet and will be added later.

---

## Español

### ¿Qué es?

Herramienta en Python que automatiza la modelación de distribución potencial de **muchas especies en una sola ejecución**. Para cada especie, usa sus registros de presencia, variables ambientales calculadas en [Google Earth Engine](https://earthengine.google.com/) (GEE) y el algoritmo MaxEnt de GEE (`ee.Classifier.amnhMaxent`). El resultado es un raster de probabilidad (idoneidad ambiental relativa) por especie, en un GeoTIFF local.

Es una herramienta de **automatización**: no decide qué especies modelar ni cómo interpretar los resultados. Esas decisiones son del usuario.

### Ejemplo incluido

El repositorio incluye un **ejemplo con datos ficticios** (`Data/ejemplo/`): especies con nombres inventados, registros de presencia aleatorios y una cuadrícula de subcuencas también ficticia. Permite probar el flujo completo, incluidas sus reglas de filtrado, sin datos reales. **No son datos de biodiversidad.** Ver [Datos de entrada](#datos-de-entrada).

Para usar tus propias especies, prepara tus archivos (catálogos, presencias, subcuencas y pseudo-ausencias) y apunta las rutas en la configuración. **Puedes modelar cualquier especie** que tenga registros de presencia y un área de estudio.

### Cómo funciona

El proceso tiene dos pasos:

| Paso | Script | Qué hace |
|---|---|---|
| **A. Áreas de modelación** | `Scripts/generar_areas_modelacion.py` | Define, para cada especie, el área de calibración **M** (unión de unidades de cuenca que contienen presencias) y el área de proyección **G** (una cuenca). La salida se calcula en **G ∩ M**. |
| **B. Modelación por lotes** | `Scripts/modelar_especies_batch.py` | Ejecuta un modelo por especie (ver pasos abajo). |

Pasos del paso B, por especie:

1. **Predictores.** Mediana de embeddings satelitales anuales de AlphaEarth Foundations (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`) en 2017–2024, más una capa de uso de suelo de MapBiomas Chile, en una grilla métrica de 250 m. Ver [Detalles técnicos](#detalles-técnicos).
2. **Selección de variables.** Muestreo local de celdas válidas y eliminación iterativa de variables con factor de inflación de la varianza (VIF ≥ 10 por defecto).
3. **Celdas de entrenamiento.** Presencias (una por celda y con *thinning* espacial de ~1 km), fondos aleatorios dentro de M y pseudo-ausencias en polígonos configurables (p. ej., áreas urbanas o de relaves). Ninguna celda aparece en dos clases.
4. **Entrenamiento.** MaxEnt en GEE, en modo de probabilidad.
5. **Exportación.** Predicción recortada a G ∩ M y descargada como GeoTIFF (EPSG:32719, 250 m) con [geedim](https://github.com/dugalh/geedim).

Cada corrida queda registrada en `Resultados/log_modelacion.csv` con su estado y sus cifras. Las corridas con raster existente se omiten, así que el proceso se puede detener y reanudar.

### Detalles técnicos

#### Fuentes de datos ambientales

| Fuente | Qué es | Uso en el proceso |
|---|---|---|
| **Google Satellite Embedding V1** (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`), producido con el modelo **AlphaEarth Foundations** de Google y Google DeepMind | Vector de embedding de **64 dimensiones** (bandas `A00`–`A63`) por píxel de **10 m** y por año, que resume la información de múltiples sensores ópticos, radar y otras fuentes. Disponible para 2017–2024. | Predictores continuos: mediana de los mosaicos anuales 2017–2024 |
| **MapBiomas Chile**, Colección 2, *clasificación final 2* (`projects/mapbiomas-chile/assets/LULC/COLLECTION-02/...`) | Clasificación anual de cobertura y uso de suelo, con una banda `classification_<año>` por año | Predictor categórico `uso_suelo`, con el año más reciente disponible hasta 2024 (respaldo: 2022) |

Notas sobre los embeddings:
- Cada dimensión es **una coordenada abstracta** del espacio de embeddings, no una variable física. Por eso el proceso no reporta importancia de variables en términos ecológicos.
- Los vectores tienen norma unitaria y no requieren normalización adicional.
- La colección se actualiza. Según su catálogo, la versión 1.1 (desde el 17 de noviembre de 2025) incluye una capa de 2017 regenerada; los resultados pueden cambiar si se usa otra versión.

#### Flujo de procesamiento por especie

1. **Área M y G.** M es la unión de unidades de cuenca con presencias; G es la cuenca de proyección. La salida se calcula en G ∩ M.
2. **Predictores.** Se construye un mosaico anual por año (2017–2024) y se calcula la mediana entre esos mosaicos. Se agrega el uso de suelo y todo se recorta a M, en EPSG:32719 y 250 m.
3. **Selección de variables (VIF).** Se descarga localmente una grilla de M (500 m, o 1 000 m si el área supera 50 000 km²), se muestrean 1 500 celdas válidas y se eliminan iterativamente las variables con VIF ≥ 10.
4. **Celdas de entrenamiento.** Se descarga localmente la grilla de 250 m con las variables seleccionadas, y se leen los valores con `rasterio`. Las presencias se asignan a celdas y se aplica *thinning* de 1 km (un punto por bloque de 4 × 4 celdas). Los fondos son celdas aleatorias de M (1:1 con las presencias). Las pseudo-ausencias son el 25 % de las presencias (mínimo 5) por cada fuente de polígonos. Ninguna celda se repite entre clases; el proceso lo verifica en cada corrida.
5. **Modelo.** `ee.Classifier.amnhMaxent()` en modo `PROBABILITY`, con parámetros por defecto (no hay ajuste de hiperparámetros). Las presencias tienen etiqueta 1; los fondos y las pseudo-ausencias, etiqueta 0. El entrenamiento usa una `FeatureCollection` de solo propiedades, subida a GEE.
6. **Predicción y exportación.** La predicción se recorta a G ∩ M y se descarga con **geedim** como GeoTIFF en EPSG:32719 a 250 m. El proceso verifica el CRS y la resolución del archivo.

#### Parámetros principales

| Parámetro | Valor | Efecto |
|---|---|---|
| `CRS_CANONICO` | `EPSG:32719` | Sistema de coordenadas de trabajo (UTM 19S) |
| `TARGET_SCALE` | 250 m | Tamaño de píxel de predictores, entrenamiento y salida |
| `EMBEDDINGS_RANGO_MEDIA` | 2017–2024 | Años de la mediana de embeddings |
| `VIF_THRESHOLD` / `VIF_NUM_PIXELS` | 10 / 1 500 | Umbral y muestra para la selección de variables |
| `THINNING_METERS` | 1 000 m | Separación mínima entre presencias de entrenamiento |
| `FONDO_RATIO` / `PSEUDO_RATIO` / `MIN_PSEUDO` | 1,0 / 0,25 / 5 | Fondos y pseudo-ausencias respecto de las presencias |
| `MIN_RECORDS` / `MIN_CELDAS_PRESENCIA` | 20 / 20 | Mínimos de registros y de bloques de presencia |
| `AREA_MODELACION_MAX_KM2` | 20 000 km² | Área M máxima para lanzar corridas nuevas |
| `GEE_REINTENTOS` / `GEE_BACKOFF_S` | 3 / 10 s | Reintentos ante errores transitorios de GEE |

#### Entorno y dependencias

Dependencias mínimas en `Scripts/requirements.txt`: `earthengine-api` ≥ 1.7.0, `geopandas` ≥ 1.1.0, `shapely` ≥ 2.1.0, `pyproj` ≥ 3.7.0, `pandas` ≥ 2.3.0, `numpy` ≥ 2.0.0, `statsmodels` ≥ 0.14.4, `scikit-learn` ≥ 1.7.0, `geedim` ≥ 2.0.0 y `rasterio` ≥ 1.5.0.

#### Reproducibilidad y costo

- Las selecciones aleatorias (fondos, pseudo-ausencias y *thinning*) usan **semillas deterministas** por especie. Con los mismos datos y la misma versión de GEE, las celdas de entrenamiento son las mismas.
- Los resultados **no son idénticos entre versiones** de los datasets de GEE, porque los embeddings y MapBiomas pueden actualizarse.
- Cada descarga de GEE consume cuota. Las áreas grandes son las más costosas: `AREA_MODELACION_MAX_KM2` ayuda a controlarlo.
- El proceso evita tablas grandes en el endpoint interactivo de GEE y descarga grillas raster con `computePixels` (vía geedim), que es más estable para predictores pesados.

### Requisitos

- **Python 3.10 o superior.** El código se desarrolló con Python 3.14; otras versiones no se han probado.
- **Windows con PowerShell 7+** para el script de instalación (`crear_entorno_local.ps1`). En otros sistemas, crea el entorno virtual y las dependencias con los comandos equivalentes.
- **Cuenta de Google Earth Engine** con un proyecto de Cloud registrado para GEE. Las descargas consumen cuota de ese proyecto.
- **Conexión estable** a internet. Una corrida puede tardar de algunos minutos a más de una hora, según el área.

### Instalación

```powershell
# 1. Crear el entorno virtual e instalar dependencias
.\Scripts\crear_entorno_local.ps1

# 2. Autenticar Google Earth Engine (solo la primera vez en esta máquina)
.\.venv\Scripts\earthengine.exe authenticate
```

Antes de correr el proceso, reemplaza el marcador `TU_PROYECTO_GEE` por tu proyecto de GEE en `Scripts/config_modelacion.py` (variable `GEE_PROJECT`).

### Inicio rápido

Con el ejemplo incluido o con tus datos ya preparados (con el ejemplo, los pasos 1 y 2 no consumen cuota de GEE; el paso 3 sí):

```powershell
# 1. Generar las áreas de modelación (paso A)
.\.venv\Scripts\python.exe .\Scripts\generar_areas_modelacion.py

# 2. Revisar el plan de corridas sin usar GEE
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --dry-run

# 3. Ejecutar el lote completo (paso B)
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py
```

Opciones útiles:

```powershell
# Solo algunas especies (nombre científico o id con guion bajo)
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --species "Ficticia alpha" ficticia_alpha

# Regenerar aunque el raster ya exista
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --force
```

Se recomienda empezar con `--dry-run` y después probar una especie con `--species`, antes de lanzar el lote completo.

### Datos de entrada

El repositorio incluye el ejemplo ficticio en `Data/ejemplo/`. Para tus propios datos, prepáralos con la estructura descrita aquí (ver también `Data/README.md`).

#### 1. Catálogo de especies

Archivos CSV con una columna llamada `Especie` (nombre científico). Cada archivo corresponde a un criterio. Las rutas y separadores se definen en `CATALOGOS` (`config_modelacion.py`).

```csv
Especie,eecc
Ficticia alpha,EN
Ficticia gamma,VU
```

Una especie puede aparecer en varios catálogos: sus criterios se acumulan.

> **Nota sobre el criterio `amenazada`.** En el ejemplo, este criterio aplica la categoría de conservación de la columna `eecc` (solo se conservan EN y CR, con excepciones definidas en `AMENAZADA_OVERRIDE`). Si usas otra clasificación, nombra tus criterios de forma distinta o ajusta `aplicar_filtro_eib` en `ee_utils_local.py`, porque el filtro quita el criterio `amenazada` cuando la columna `eecc` no permite confirmarlo.

#### 2. Registros de presencia

Un CSV por especie, en una de las carpetas de `PRESENCIAS_DIRS`, con nombre en minúsculas y guion bajo: `genero_especie.csv` (p. ej., `percilia_irwini.csv`).

Columnas obligatorias (los nombres se normalizan automáticamente):

| Columna | Alias aceptado | Descripción |
|---|---|---|
| `Anio` | `year` | Año del registro |
| `latitud` | `latitude` | Latitud en grados decimales (WGS 84) |
| `longitud` | `longitude` | Longitud en grados decimales (WGS 84) |

El separador es coma (`,`). Otras columnas se ignoran.

#### 3. Unidades de cuenca (Chile: subcuencas BNA)

Para el paso A, el área M se construye a partir de la **Base Nacional de Aguas (BNA)** de la Dirección General de Aguas (DGA), en `Data/Subcuencas/SubCuencas_BNA/SubCuencas_BNA.shp`. Los campos usados son `COD_SUBC`, `NOM_SUBC` y `COD_CUEN`.

#### 4. Polígonos de pseudo-ausencias

Dos archivos GeoJSON de polígonos (urbanos y de relaves), cuyas rutas se configuran en `PSEUDOAUSENCIAS`. Son los polígonos donde se muestrean pseudo-ausencias. En el ejemplo están en `Data/ejemplo/pseudoausencias/`. Si no tienes fuentes equivalentes, puedes preparar tus propios polígonos con el mismo formato.

### Adaptar a otra región o a otros datos

- **Sin BNA.** El paso A depende de subcuencas chilenas. Si trabajas con otra región, puedes saltarte el paso A y entregar tú mismo:
  - `Data/Areas_Modelacion/area_<especie>.geojson`, una geometría M por especie, y
  - el archivo de la región de proyección G, indicado en `AREA_PROYECCION_GEOJSON`.
- **Zona UTM.** La grilla de trabajo está en EPSG:32719 (UTM 19S). Para otra zona, cambia `CRS_CANONICO`. El código también asume zonas UTM 18S y 19S en algunos cálculos (`generar_areas_modelacion.py`); revísalo si tu área queda fuera de esas zonas.
- **Uso de suelo.** La capa de uso de suelo está ligada a MapBiomas Chile (`MAPBIOMAS_ID`). Fuera de Chile, reemplázala por otra capa o elimínala en `preparar_predictores`.

### Configuración

Todos los parámetros están en `Scripts/config_modelacion.py`. Los valores por defecto corresponden al ejemplo. Los más relevantes:

| Parámetro | Descripción |
|---|---|
| `GEE_PROJECT` | Proyecto de Google Earth Engine que se usará para las descargas |
| `CATALOGOS` | Catálogos de especies y sus criterios |
| `PRESENCIAS_DIRS` | Carpetas con los CSV de presencia |
| `SUBCUENCAS_SHP` | Shapefile de unidades de cuenca (paso A) |
| `CUENCA_PROYECCION_COD` | Código de la cuenca de proyección G |
| `CRS_CANONICO` / `TARGET_SCALE` | Sistema de coordenadas y tamaño de píxel de trabajo |
| `EMBEDDINGS_RANGO_MEDIA` | Años usados para la mediana de embeddings |
| `MIN_RECORDS` / `MIN_CELDAS_PRESENCIA` | Mínimos de registros y de celdas para modelar una especie |
| `THINNING_METERS` | Distancia mínima entre presencias usadas en el entrenamiento |
| `FONDO_RATIO` / `PSEUDO_RATIO` | Cantidad de fondos y pseudo-ausencias respecto de las presencias |
| `VIF_THRESHOLD` | Umbral de VIF para eliminar variables |
| `AREA_MODELACION_MAX_KM2` | Área M máxima para lanzar una corrida nueva (control de cuota) |

### Salidas

| Ruta | Contenido |
|---|---|
| `Data/Areas_Modelacion/area_<especie>.geojson` | Área de calibración M de cada especie |
| `Data/Areas_Modelacion/areas_modelacion.gpkg` | Todas las áreas en un solo GeoPackage |
| `Resultados/resumen_areas_modelacion.csv` | Resumen del paso A (subcuencas, puntos y área por especie) |
| `Resultados/Modelos_Distribucion/<especie>/<especie>.tif` | Probabilidad de idoneidad en G ∩ M (EPSG:32719, 250 m) |
| `Resultados/log_modelacion.csv` | Bitácora del paso B: estado y cifras de cada corrida |

Los valores de los rasters van de 0 a 1 y representan **idoneidad ambiental relativa**, no probabilidad de presencia confirmada.

### Limitaciones y uso responsable

- **Idoneidad, no presencia.** Un modelo entrenado con datos de presencia indica qué tan parecidas son las condiciones de cada celda a las de los registros. No confirma que la especie esté allí.
- **La ausencia de registros no equivale a ausencia de la especie.** Un registro faltante puede deberse a falta de muestreo, de detección o de publicación de datos.
- **Sesgo de muestreo.** Los modelos reproducen el esfuerzo de muestreo de los datos. Las zonas más visitadas tienden a quedar sobrerrepresentadas.
- **Validación pendiente.** El proceso aún no incluye una etapa de validación cuantitativa (por ejemplo, AUC o evaluación con datos independientes). Se añadirá en una versión posterior. Mientras tanto, los resultados deben interpretarse como un modelo preliminar, sin métricas de desempeño.
- **Resolución.** Los predictores se procesan a 250 m. Especies de distribución muy localizada pueden requerir una resolución más fina y datos más precisos.
- **Datos sensibles.** Publicar coordenadas exactas de especies amenazadas puede exponerlas a perturbación. Considera generalizar o agregar esas coordenadas antes de compartir resultados.
- **Cuota de GEE.** Las áreas grandes consumen más cuota y tiempo. `AREA_MODELACION_MAX_KM2` ayuda a controlarlo.

### Estructura del repositorio

```
.
├── Scripts/
│   ├── config_modelacion.py          # Configuración central (rutas, GEE, parámetros)
│   ├── ee_utils_local.py             # Utilidades: GEE, catálogos, presencias, VIF, pseudo-ausencias
│   ├── generar_areas_modelacion.py   # Paso A: áreas de modelación
│   ├── modelar_especies_batch.py     # Paso B: modelación por lotes
│   ├── generar_datos_ficticios.py    # Genera el ejemplo ficticio de Data/ejemplo/
│   ├── crear_entorno_local.ps1       # Crea el entorno virtual e instala dependencias
│   └── requirements.txt
├── Data/                             # Datos de entrada: ejemplo ficticio en Data/ejemplo/ (ver Data/README.md)
├── Resultados/                       # Salidas (generadas al ejecutar)
├── LICENSE
└── README.md
```

### Licencia

El código se distribuye bajo licencia **MIT** (ver [LICENSE](LICENSE)). Los datos que uses (registros de presencia, BNA, MapBiomas, datasets de GEE, etc.) se rigen por sus propias licencias y condiciones de uso, que debes revisar antes de publicar resultados.

---

## English

### What is it?

A Python tool that automates **species distribution modelling for many species in a single run**. For each species, it uses presence records, environmental variables computed in [Google Earth Engine](https://earthengine.google.com/) (GEE), and GEE's MaxEnt implementation (`ee.Classifier.amnhMaxent`). The output is a probability raster (relative environmental suitability) per species, saved locally as GeoTIFF.

It is an **automation** tool: it does not decide which species to model or how to interpret the results. Those decisions belong to the user.

### Included example

The repository includes an **example with fictitious data** (`Data/ejemplo/`): species with invented names, random presence records and a also fictitious sub-basin grid. It lets you run the full workflow, including its filtering rules, without real data. **It is not biodiversity data.** See [Input data](#input-data).

To use your own species, prepare your files (catalogues, presence records, sub-basins and pseudo-absences) and point the paths in the configuration. **You can model any species** that has presence records and a study area.

### How it works

The process has two steps:

| Step | Script | What it does |
|---|---|---|
| **A. Modelling areas** | `Scripts/generar_areas_modelacion.py` | For each species, defines the calibration area **M** (union of basin units containing presences) and a projection area **G** (one basin). Output is computed on **G ∩ M**. |
| **B. Batch modelling** | `Scripts/modelar_especies_batch.py` | Runs one model per species (steps below). |

Step B, per species:

1. **Predictors.** Median of annual AlphaEarth Foundations satellite embeddings (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`) for 2017–2024, plus a land-cover layer from MapBiomas Chile, on a 250 m metric grid. See [Technical details](#technical-details).
2. **Variable selection.** Local sampling of valid cells and iterative removal of variables with variance inflation factor (VIF ≥ 10 by default).
3. **Training cells.** Presences (one per cell, spatially thinned to ~1 km), random background cells within M, and pseudo-absences in configurable polygons (e.g. urban or tailings areas). No cell belongs to two classes.
4. **Training.** MaxEnt in GEE, probability output mode.
5. **Export.** Prediction clipped to G ∩ M and downloaded as GeoTIFF (EPSG:32719, 250 m) with [geedim](https://github.com/dugalh/geedim).

Each run is logged in `Resultados/log_modelacion.csv` with its status and figures. Runs with an existing raster are skipped, so the process can be stopped and resumed.

### Technical details

#### Environmental data sources

| Source | What it is | Use in the process |
|---|---|---|
| **Google Satellite Embedding V1** (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`), produced with the **AlphaEarth Foundations** model by Google and Google DeepMind | Annual embedding vector of **64 dimensions** (bands `A00`–`A63`) per **10 m** pixel, summarising optical, radar and other multi-source observations. Available for 2017–2024. | Continuous predictors: median of the 2017–2024 annual mosaics |
| **MapBiomas Chile**, Collection 2, *clasificación final 2* (`projects/mapbiomas-chile/assets/LULC/COLLECTION-02/...`) | Annual land-cover and land-use classification, with one `classification_<year>` band per year | Categorical predictor `uso_suelo`, using the most recent year available up to 2024 (fallback: 2022) |

Notes on the embeddings:
- Each dimension is an **abstract coordinate** in the embedding space, not a physical variable. For this reason the process does not report ecological variable importance.
- Vectors have unit norm and need no additional normalisation.
- The collection is updated. According to its catalogue, version 1.1 (from 17 November 2025) includes a regenerated 2017 layer; results may change with other versions.

#### Per-species processing flow

1. **Areas M and G.** M is the union of basin units containing presences; G is the projection basin. Output is computed on G ∩ M.
2. **Predictors.** One annual mosaic per year (2017–2024) is built and the median across those mosaics is computed. Land use is added, and everything is clipped to M, in EPSG:32719 at 250 m.
3. **Variable selection (VIF).** A grid of M is downloaded locally (500 m, or 1 000 m if the area exceeds 50 000 km²), 1 500 valid cells are sampled, and variables with VIF ≥ 10 are removed iteratively.
4. **Training cells.** The 250 m grid with the selected variables is downloaded locally and read with `rasterio`. Presences are assigned to cells and thinned to 1 km (one point per 4 × 4 cell block). Background points are random cells within M (1:1 with presences). Pseudo-absences are 25 % of the presences (minimum 5) per polygon source. No cell is shared between classes; the process checks this on every run.
5. **Model.** `ee.Classifier.amnhMaxent()` in `PROBABILITY` mode, with default parameters (no hyperparameter tuning). Presences have label 1; background and pseudo-absences have label 0. Training uses a property-only `FeatureCollection` uploaded to GEE.
6. **Prediction and export.** The prediction is clipped to G ∩ M and downloaded with **geedim** as a GeoTIFF in EPSG:32719 at 250 m. The process checks the file's CRS and resolution.

#### Main parameters

| Parameter | Value | Effect |
|---|---|---|
| `CRS_CANONICO` | `EPSG:32719` | Working coordinate system (UTM 19S) |
| `TARGET_SCALE` | 250 m | Pixel size for predictors, training and output |
| `EMBEDDINGS_RANGO_MEDIA` | 2017–2024 | Years in the embedding median |
| `VIF_THRESHOLD` / `VIF_NUM_PIXELS` | 10 / 1 500 | Threshold and sample for variable selection |
| `THINNING_METERS` | 1 000 m | Minimum separation between training presences |
| `FONDO_RATIO` / `PSEUDO_RATIO` / `MIN_PSEUDO` | 1.0 / 0.25 / 5 | Background and pseudo-absences relative to presences |
| `MIN_RECORDS` / `MIN_CELDAS_PRESENCIA` | 20 / 20 | Minimum records and presence blocks |
| `AREA_MODELACION_MAX_KM2` | 20 000 km² | Maximum M area for starting new runs |
| `GEE_REINTENTOS` / `GEE_BACKOFF_S` | 3 / 10 s | Retries on transient GEE errors |

#### Environment and dependencies

Minimum dependencies in `Scripts/requirements.txt`: `earthengine-api` ≥ 1.7.0, `geopandas` ≥ 1.1.0, `shapely` ≥ 2.1.0, `pyproj` ≥ 3.7.0, `pandas` ≥ 2.3.0, `numpy` ≥ 2.0.0, `statsmodels` ≥ 0.14.4, `scikit-learn` ≥ 1.7.0, `geedim` ≥ 2.0.0 and `rasterio` ≥ 1.5.0.

#### Reproducibility and cost

- Random selections (background, pseudo-absences and thinning) use **deterministic seeds** per species. With the same data and the same GEE dataset versions, the training cells are the same.
- Results are **not identical across dataset versions**, because the embeddings and MapBiomas may be updated.
- Each GEE download consumes quota. Large areas are the most expensive: `AREA_MODELACION_MAX_KM2` helps control this.
- The process avoids large tables on GEE's interactive endpoint and downloads raster grids with `computePixels` (via geedim), which is more stable for heavy predictors.

### Requirements

- **Python 3.10 or newer.** The code was developed with Python 3.14; other versions have not been tested.
- **Windows with PowerShell 7+** for the setup script (`crear_entorno_local.ps1`). On other systems, create the virtual environment and install dependencies with equivalent commands.
- **Google Earth Engine account** with a Cloud project enabled for GEE. Downloads consume that project's quota.
- **Stable internet connection.** A run can take from a few minutes to over an hour, depending on the area.

### Installation

```powershell
# 1. Create the virtual environment and install dependencies
.\Scripts\crear_entorno_local.ps1

# 2. Authenticate Google Earth Engine (only the first time on this machine)
.\.venv\Scripts\earthengine.exe authenticate
```

Before running, replace the placeholder `TU_PROYECTO_GEE` with your GEE project in `Scripts/config_modelacion.py` (variable `GEE_PROJECT`).

### Quick start

With the included example or your prepared data (with the example, steps 1 and 2 do not use GEE quota; step 3 does):

```powershell
# 1. Generate modelling areas (step A)
.\.venv\Scripts\python.exe .\Scripts\generar_areas_modelacion.py

# 2. Review the run plan without using GEE
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --dry-run

# 3. Run the full batch (step B)
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py
```

Useful options:

```powershell
# Only some species (scientific name or id with underscores)
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --species "Ficticia alpha" ficticia_alpha

# Regenerate even if the raster already exists
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --force
```

It is recommended to start with `--dry-run`, then test one species with `--species`, before running the full batch.

### Input data

The repository includes the fictitious example in `Data/ejemplo/`. For your own data, prepare it following the structure described here (see also `Data/README.md`).

#### 1. Species catalogue

CSV files with a column named `Especie` (scientific name). Each file corresponds to one criterion. Paths and separators are set in `CATALOGOS` (`config_modelacion.py`).

```csv
Especie,eecc
Ficticia alpha,EN
Ficticia gamma,VU
```

A species may appear in several catalogues; its criteria are combined.

> **Note on the `amenazada` criterion.** In the example, this criterion applies the conservation category in the `eecc` column (only EN and CR are kept, with exceptions defined in `AMENAZADA_OVERRIDE`). If you use a different classification, name your criteria differently or adjust `aplicar_filtro_eib` in `ee_utils_local.py`, because the filter removes the `amenazada` criterion when `eecc` cannot confirm it.

#### 2. Presence records

One CSV per species, in one of the folders listed in `PRESENCIAS_DIRS`, named in lowercase with underscores: `genus_species.csv` (e.g. `percilia_irwini.csv`).

Required columns (names are normalised automatically):

| Column | Accepted alias | Description |
|---|---|---|
| `Anio` | `year` | Year of the record |
| `latitud` | `latitude` | Latitude in decimal degrees (WGS 84) |
| `longitud` | `longitude` | Longitude in decimal degrees (WGS 84) |

The separator is a comma (`,`). Other columns are ignored.

#### 3. Basin units (Chile: BNA sub-basins)

For step A, the area M is built from the **Base Nacional de Aguas (BNA)** of the Chilean *Dirección General de Aguas* (DGA), at `Data/Subcuencas/SubCuencas_BNA/SubCuencas_BNA.shp`. Fields used: `COD_SUBC`, `NOM_SUBC` and `COD_CUEN`.

#### 4. Pseudo-absence polygons

Two GeoJSON polygon files (urban and tailings) whose paths are set in `PSEUDOAUSENCIAS`. These are the polygons where pseudo-absences are sampled. In the example they are in `Data/ejemplo/pseudoausencias/`. If you lack equivalent sources, prepare your own polygons in the same format.

### Adapting to another region or other data

- **Without BNA.** Step A depends on Chilean sub-basins. For another region, you can skip step A and provide:
  - `Data/Areas_Modelacion/area_<species>.geojson`, one M geometry per species, and
  - the projection area G file, set in `AREA_PROYECCION_GEOJSON`.
- **UTM zone.** The working grid is EPSG:32719 (UTM 19S). For another zone, change `CRS_CANONICO`. Some calculations also assume UTM zones 18S and 19S (`generar_areas_modelacion.py`); review them if your area falls outside those zones.
- **Land cover.** The land-cover layer is tied to MapBiomas Chile (`MAPBIOMAS_ID`). Outside Chile, replace it with another layer or remove it in `preparar_predictores`.

### Configuration

All parameters are in `Scripts/config_modelacion.py`. Default values correspond to the example. Most relevant:

| Parameter | Description |
|---|---|
| `GEE_PROJECT` | Google Earth Engine project used for downloads |
| `CATALOGOS` | Species catalogues and their criteria |
| `PRESENCIAS_DIRS` | Folders with presence CSV files |
| `SUBCUENCAS_SHP` | Basin-unit shapefile (step A) |
| `CUENCA_PROYECCION_COD` | Code of the projection basin G |
| `CRS_CANONICO` / `TARGET_SCALE` | Working coordinate system and pixel size |
| `EMBEDDINGS_RANGO_MEDIA` | Years used for the embedding median |
| `MIN_RECORDS` / `MIN_CELDAS_PRESENCIA` | Minimum records and cells required to model a species |
| `THINNING_METERS` | Minimum distance between presences used in training |
| `FONDO_RATIO` / `PSEUDO_RATIO` | Number of background and pseudo-absence points relative to presences |
| `VIF_THRESHOLD` | VIF threshold for removing variables |
| `AREA_MODELACION_MAX_KM2` | Maximum M area for starting a new run (quota control) |

### Outputs

| Path | Content |
|---|---|
| `Data/Areas_Modelacion/area_<species>.geojson` | Calibration area M for each species |
| `Data/Areas_Modelacion/areas_modelacion.gpkg` | All areas in one GeoPackage |
| `Resultados/resumen_areas_modelacion.csv` | Step A summary (sub-basins, points and area per species) |
| `Resultados/Modelos_Distribucion/<species>/<species>.tif` | Suitability in G ∩ M (EPSG:32719, 250 m) |
| `Resultados/log_modelacion.csv` | Step B log: status and figures per run |

Raster values range from 0 to 1 and represent **relative environmental suitability**, not confirmed probability of presence.

### Limitations and responsible use

- **Suitability, not presence.** A model trained on presence data indicates how similar the conditions of each cell are to those of the records. It does not confirm that the species is there.
- **Absence of records is not absence of the species.** A missing record may reflect lack of sampling, detection or data publication.
- **Sampling bias.** Models reflect the sampling effort in the data. Heavily surveyed areas tend to be overrepresented.
- **Validation pending.** The process does not yet include a quantitative validation stage (for example AUC or evaluation with independent data). It will be added in a later version. Until then, results should be interpreted as a preliminary model without performance metrics.
- **Resolution.** Predictors are processed at 250 m. Very localised species may require finer resolution and more precise data.
- **Sensitive data.** Publishing exact coordinates of threatened species may expose them to disturbance. Consider generalising or withholding those coordinates before sharing results.
- **GEE quota.** Large areas consume more quota and time. `AREA_MODELACION_MAX_KM2` helps control this.

### Repository structure

```
.
├── Scripts/
│   ├── config_modelacion.py          # Central configuration (paths, GEE, parameters)
│   ├── ee_utils_local.py             # Utilities: GEE, catalogues, presences, VIF, pseudo-absences
│   ├── generar_areas_modelacion.py   # Step A: modelling areas
│   ├── modelar_especies_batch.py     # Step B: batch modelling
│   ├── generar_datos_ficticios.py    # Generates the fictitious example in Data/ejemplo/
│   ├── crear_entorno_local.ps1       # Creates the virtual environment and installs dependencies
│   └── requirements.txt
├── Data/                             # Input data: fictitious example in Data/ejemplo/ (see Data/README.md)
├── Resultados/                       # Outputs (generated when running)
├── LICENSE
└── README.md
```

### License

The code is released under the **MIT** license (see [LICENSE](LICENSE)). Data you use (presence records, BNA, MapBiomas, GEE datasets, etc.) is governed by its own licences and terms of use, which you should review before publishing results.
