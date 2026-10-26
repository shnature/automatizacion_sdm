# Automatización de modelación de distribución de especies por lotes

**Batch species distribution modelling automation** · Python · Google Earth Engine · MaxEnt

Idioma / Language: [Español](#español) · [English](#english)

---

## Español

### ¿Qué es?

Herramienta en Python que automatiza la modelación de distribución potencial de **muchas especies en una sola ejecución**. Para cada especie, usa sus registros de presencia, variables ambientales calculadas en [Google Earth Engine](https://earthengine.google.com/) (GEE) y el algoritmo MaxEnt de GEE (`ee.Classifier.amnhMaxent`). El resultado es un raster de probabilidad (idoneidad ambiental relativa) por especie, en un GeoTIFF local.

Es una herramienta de **automatización**: no decide qué especies modelar ni cómo interpretar los resultados. Esas decisiones son del usuario.

### Ejemplo incluido

El flujo se diseñó y probó con un **ejemplo**: especies de catálogos de especies amenazadas, singulares, de valor cultural y de distribución restringida, en la cuenca del río Biobío (Chile). Los catálogos y los registros de presencia **no se incluyen** en este repositorio (ver [Datos de entrada](#datos-de-entrada)).

El ejemplo muestra cómo opera el proceso. **Puedes modelar cualquier especie** que tenga registros de presencia y un área de estudio: basta con preparar tus propios archivos y, si lo necesitas, cambiar la configuración.

### Cómo funciona

El proceso tiene dos pasos:

| Paso | Script | Qué hace |
|---|---|---|
| **A. Áreas de modelación** | `Scripts/generar_areas_modelacion.py` | Define, para cada especie, el área de calibración **M** (unión de unidades de cuenca que contienen presencias) y el área de proyección **G** (una cuenca). La salida se calcula en **G ∩ M**. |
| **B. Modelación por lotes** | `Scripts/modelar_especies_batch.py` | Ejecuta un modelo por especie (ver pasos abajo). |

Pasos del paso B, por especie:

1. **Predictores.** Mediana de embeddings satelitales anuales de GEE (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`) en un rango de años configurable, más una capa de uso de suelo (MapBiomas Chile), en una grilla métrica de 250 m.
2. **Selección de variables.** Muestreo local de celdas válidas y eliminación iterativa de variables con factor de inflación de la varianza (VIF ≥ 10 por defecto).
3. **Celdas de entrenamiento.** Presencias (una por celda y con *thinning* espacial de ~1 km), fondos aleatorios dentro de M y pseudo-ausencias en polígonos configurables (p. ej., áreas urbanas o de relaves). Ninguna celda aparece en dos clases.
4. **Entrenamiento.** MaxEnt en GEE, en modo de probabilidad.
5. **Exportación.** Predicción recortada a G ∩ M y descargada como GeoTIFF (EPSG:32719, 250 m) con [geedim](https://github.com/dugalh/geedim).

Cada corrida queda registrada en `Resultados/log_modelacion.csv` con su estado y sus cifras. Las corridas con raster existente se omiten, así que el proceso se puede detener y reanudar.

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

Con los datos de entrada ya preparados:

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
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --species "Percilia irwini" percilia_irwini

# Regenerar aunque el raster ya exista
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --force
```

Se recomienda empezar con `--dry-run` y después probar una especie con `--species`, antes de lanzar el lote completo.

### Datos de entrada

Los datos no vienen en el repositorio. Debes prepararlos en la carpeta `Data/` (ver `Data/README.md`).

#### 1. Catálogo de especies

Archivos CSV con una columna llamada `Especie` (nombre científico). Cada archivo corresponde a un criterio. Las rutas y separadores se definen en `CATALOGOS` (`config_modelacion.py`).

```csv
Especie,eecc
Percilia irwini,EN
Chloraea disoides,VU
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

Dos archivos GeoJSON en `Data/Poligonos_pseudoausencias/`: `Areas_Pobladas_Chile.geojson` y `RelavesMineros.geojson` (nombres configurables en `PSEUDOAUSENCIAS`). Son polígonos donde se muestrean pseudo-ausencias. Si no tienes fuentes equivalentes, puedes preparar tus propios polígonos con el mismo formato.

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
- **Sin validación cuantitativa incluida.** El proceso no calcula métricas de desempeño (como AUC). Si las necesitas, deben añadirse como parte de tu análisis.
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
│   ├── crear_entorno_local.ps1       # Crea el entorno virtual e instala dependencias
│   └── requirements.txt
├── Data/                             # Datos de entrada (no incluidos; ver Data/README.md)
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

The workflow was designed and tested with an **example**: species from catalogues of threatened, singular, culturally valued and range-restricted species in the Biobío river basin (Chile). The catalogues and presence records are **not included** in this repository (see [Input data](#input-data)).

The example shows how the process works. **You can model any species** that has presence records and a study area: prepare your own files and, if needed, change the configuration.

### How it works

The process has two steps:

| Step | Script | What it does |
|---|---|---|
| **A. Modelling areas** | `Scripts/generar_areas_modelacion.py` | For each species, defines the calibration area **M** (union of basin units containing presences) and a projection area **G** (one basin). Output is computed on **G ∩ M**. |
| **B. Batch modelling** | `Scripts/modelar_especies_batch.py` | Runs one model per species (steps below). |

Step B, per species:

1. **Predictors.** Median of annual GEE satellite embeddings (`GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL`) over a configurable year range, plus a land-cover layer (MapBiomas Chile), on a 250 m metric grid.
2. **Variable selection.** Local sampling of valid cells and iterative removal of variables with variance inflation factor (VIF ≥ 10 by default).
3. **Training cells.** Presences (one per cell, spatially thinned to ~1 km), random background cells within M, and pseudo-absences in configurable polygons (e.g. urban or tailings areas). No cell belongs to two classes.
4. **Training.** MaxEnt in GEE, probability output mode.
5. **Export.** Prediction clipped to G ∩ M and downloaded as GeoTIFF (EPSG:32719, 250 m) with [geedim](https://github.com/dugalh/geedim).

Each run is logged in `Resultados/log_modelacion.csv` with its status and figures. Runs with an existing raster are skipped, so the process can be stopped and resumed.

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

With input data already prepared:

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
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --species "Percilia irwini" percilia_irwini

# Regenerate even if the raster already exists
.\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py --force
```

It is recommended to start with `--dry-run`, then test one species with `--species`, before running the full batch.

### Input data

Data is not included in the repository. Prepare it in the `Data/` folder (see `Data/README.md`).

#### 1. Species catalogue

CSV files with a column named `Especie` (scientific name). Each file corresponds to one criterion. Paths and separators are set in `CATALOGOS` (`config_modelacion.py`).

```csv
Especie,eecc
Percilia irwini,EN
Chloraea disoides,VU
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

Two GeoJSON files in `Data/Poligonos_pseudoausencias/`: `Areas_Pobladas_Chile.geojson` and `RelavesMineros.geojson` (names configurable in `PSEUDOAUSENCIAS`). These are polygons where pseudo-absences are sampled. If you lack equivalent sources, prepare your own polygons in the same format.

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
- **No quantitative validation included.** The process does not compute performance metrics (such as AUC). If you need them, add them as part of your analysis.
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
│   ├── crear_entorno_local.ps1       # Creates the virtual environment and installs dependencies
│   └── requirements.txt
├── Data/                             # Input data (not included; see Data/README.md)
├── Resultados/                       # Outputs (generated when running)
├── LICENSE
└── README.md
```

### License

The code is released under the **MIT** license (see [LICENSE](LICENSE)). Data you use (presence records, BNA, MapBiomas, GEE datasets, etc.) is governed by its own licences and terms of use, which you should review before publishing results.
