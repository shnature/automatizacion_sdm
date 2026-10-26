# =============================================================================
# Esc: crear_entorno_local.ps1
# Crear el entorno virtual (venv) del proyecto e instalar dependencias.
#
# Uso:
#   .\Scripts\crear_entorno_local.ps1
#
# Tras crear el entorno, autenticar Google Earth Engine SOLO la primera vez:
#   .\.venv\Scripts\earthengine.exe authenticate
# (o simplemente ejecutar modelar_especies_batch.py y seguir el flujo interactivo)
# =============================================================================

$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $rootDir ".venv"
$reqPath = Join-Path $PSScriptRoot "requirements.txt"

Write-Host "== Entorno de modelación de especies ==" -ForegroundColor Cyan

# 1. Crear venv (si no existe)
if (-not (Test-Path -LiteralPath (Join-Path $venvDir "pyvenv.cfg"))) {
    Write-Host "[1/3] Creando $venvDir ..."
    python -m venv $venvDir
} else {
    Write-Host "[1/3] El venv ya existe en $venvDir (se omite la creación)."
}

$venvPython = Join-Path $venvDir "Scripts\python.exe"

# 2. Actualizar pip
Write-Host "[2/3] Actualizando pip..."
& $venvPython -m pip install --upgrade pip wheel

# 3. Instalar dependencias
Write-Host "[3/3] Instalando dependencias desde requirements.txt ..."
& $venvPython -m pip install -r $reqPath

Write-Host ""
Write-Host "Entorno listo. Para usarlo:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Primera vez con Google Earth Engine (solo si no hay credenciales):" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\earthengine.exe authenticate"
Write-Host ""
Write-Host "Generar áreas de modelación:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\python.exe .\Scripts\generar_areas_modelacion.py"
Write-Host ""
Write-Host "Modelación por lotes:" -ForegroundColor Yellow
Write-Host "  .\.venv\Scripts\python.exe .\Scripts\modelar_especies_batch.py [--species percilia_irwini] [--dry-run]"
