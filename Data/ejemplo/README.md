# Datos FICTICIOS de ejemplo / FICTITIOUS example data

**Todo lo contenido en esta carpeta es ficticio.** Las especies tienen nombres inventados, los registros de presencia son aleatorios, la cuadrícula de subcuencas no corresponde a ninguna cuenca real y los polígonos de pseudo-ausencias son formas sencillas.
**All contents of this folder are fictitious.** Species names are invented, presence records are random, the sub-basin grid does not match any real basin, and the pseudo-absence polygons are simple shapes.

No deben usarse como datos de biodiversidad ni para ningún análisis real.
They must not be used as biodiversity data or for any real analysis.

## Contenido / Contents

| Carpeta | Contenido |
|---|---|
| `catalogos/` | Catálogos con dos criterios: amenazada (EN/CR/VU) y singular |
| `presencias/` | Un CSV por especie con registros aleatorios dentro de una zona ficticia |
| `subcuencas/` | Cuadrícula de 5 × 5 celdas (cuenca ficticia `900`) |
| `pseudoausencias/` | Polígonos urbanos y de relaves ficticios |

## Casos que muestra el ejemplo / What the example demonstrates

- **Ficticia alpha** (EN) y **Ficticia beta** (CR): se modelan.
- **Ficticia gamma** (VU): el filtro EN/CR le quita el criterio `amenazada` y no tiene otro criterio, así que no se modela.
- **Ejemplar delta** (singular): se modela.
- **Ejemplar epsilon** (singular, 12 registros): se omite por `MIN_RECORDS`.

## Regenerar / Regenerate

Estos archivos se generan con `Scripts/generar_datos_ficticios.py` (semilla fija, resultados reproducibles).
These files are produced by `Scripts/generar_datos_ficticios.py` (fixed seed, reproducible results).
