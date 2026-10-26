# Datos de entrada / Input data

Esta carpeta no incluye datos. Prepara aquí tus archivos antes de ejecutar el proceso.
This folder ships without data. Prepare your files here before running the process.

## Estructura esperada / Expected structure

```
Data/
├── Presencias/
│   ├── Presencias_modelacion/
│   │   ├── amenazadas/              # un CSV por especie: genus_species.csv
│   │   └── no_amenazadas/           # (opcional) según PRESENCIAS_DIRS
│   ├── mi_catalogo.csv              # catálogo(s) de especies (columna "Especie")
│   └── ...
├── Subcuencas/
│   └── SubCuencas_BNA/
│       └── SubCuencas_BNA.shp       # (+ .dbf, .shx, .prj, ...) BNA de la DGA
├── Poligonos_pseudoausencias/
│   ├── Areas_Pobladas_Chile.geojson
│   └── RelavesMineros.geojson
└── Areas_Modelacion/                # generado por generar_areas_modelacion.py
```

Las rutas exactas se definen en `Scripts/config_modelacion.py`.
Exact paths are defined in `Scripts/config_modelacion.py`.

## Formatos / Formats

- **Presencias:** CSV separado por comas, con columnas `Anio` (o `year`), `latitud` (o `latitude`) y `longitud` (o `longitude`), en grados decimales WGS 84. Nombre del archivo en minúsculas con guion bajo.
- **Catálogos:** CSV con una columna `Especie`. Ver la sección de datos de entrada en el README principal.
- **BNA:** shapefile con los campos `COD_SUBC`, `NOM_SUBC` y `COD_CUEN`.
- **Pseudo-ausencias:** GeoJSON de polígonos.

## Licencias / Licences

Los datos deben obtenerse de sus fuentes oficiales y usarse según sus licencias (por ejemplo, GBIF, DGA-BNA, MapBiomas o registros propios). No se redistribuyen en este repositorio.
Obtain data from official sources and use it under their licences (for example GBIF, DGA-BNA, MapBiomas, or your own records). They are not redistributed in this repository.
