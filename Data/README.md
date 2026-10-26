# Datos de entrada / Input data

Esta carpeta incluye únicamente el **ejemplo ficticio** en `Data/ejemplo/` (ver `Data/ejemplo/README.md`). Para usar tus propios datos, crea otras carpetas y apunta las rutas en `Scripts/config_modelacion.py`.
This folder only includes the **fictitious example** in `Data/ejemplo/` (see `Data/ejemplo/README.md`). To use your own data, create other folders and point the paths in `Scripts/config_modelacion.py`.

## Formatos / Formats

- **Presencias:** CSV separado por comas, con columnas `Anio` (o `year`), `latitud` (o `latitude`) y `longitud` (o `longitude`), en grados decimales WGS 84. Nombre del archivo en minúsculas con guion bajo.
- **Catálogos:** CSV con una columna `Especie` (y `eecc` si usas el criterio `amenazada`).
- **Subcuencas:** shapefile con los campos `COD_SUBC`, `NOM_SUBC` y `COD_CUEN`.
- **Pseudo-ausencias:** GeoJSON de polígonos.

## Datos reales / Real data

Obtén los datos de sus fuentes oficiales y úsalos según sus licencias (por ejemplo, GBIF, DGA-BNA, MapBiomas o registros propios). No se redistribuyen en este repositorio.
Obtain data from official sources and use it under their licences (for example GBIF, DGA-BNA, MapBiomas, or your own records). They are not redistributed in this repository.
