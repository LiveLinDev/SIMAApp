# SIMA con mini-format sobre una base SQLite local y DeepSeek.
#
#   .\demo_mini.ps1                   abre SIMA en http://127.0.0.1:8010 con el lector mini-format
#   .\demo_mini.ps1 -Lector legado    mismo SIMA con el lector anterior (parse_mini), para comparar
#   .\demo_mini.ps1 -Regenerar        vuelve a crear .env.demo desde .env
#
# La primera vez crea .env.demo a partir de .env: misma configuracion, base SQLite propia (db_mini.sqlite3)
# y DeepSeek como proveedor. La clave se copia de DEEPSEEK_APIKEY / DEEPSEEK_API_KEY / CLOUD_API_KEY sin
# mostrarse. .env.demo y db_mini.sqlite3 estan en .gitignore: no se suben al repositorio.
param(
    [ValidateSet("minifmt", "legado")][string]$Lector = "minifmt",
    [int]$Puerto = 8010,
    [switch]$Regenerar
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$demo = Join-Path $PSScriptRoot ".env.demo"

if ($Regenerar -or -not (Test-Path $demo)) {
    if (-not (Test-Path ".env")) { throw "No existe .env: copia .env.example y agrega DEEPSEEK_APIKEY." }
    $lineas = Get-Content ".env" -Encoding UTF8
    $clave = ""
    foreach ($nombre in "DEEPSEEK_APIKEY", "DEEPSEEK_API_KEY", "CLOUD_API_KEY") {
        $l = $lineas | Where-Object { $_ -match "^$nombre=(.+)$" } | Select-Object -First 1
        if ($l -and -not $clave) { $clave = ($l -split "=", 2)[1].Trim().Trim('"').Trim("'") }
    }
    if (-not $clave) { throw "Agrega DEEPSEEK_APIKEY=<clave> en .env" }
    $reemplazar = "DB_ENGINE", "SQLITE_NAME", "DATABASE_URL", "CLOUD_PROVIDER", "CLOUD_API_BASE", "CLOUD_API_KEY",
                  "CLOUD_MODEL", "CLOUD_VERIFICATION_MODEL", "CLOUD_LABEL", "CLOUD_TOKENS_PER_MINUTE", "SIMA_LECTOR"
    $salida = $lineas | Where-Object { $l = $_; -not ($reemplazar | Where-Object { $l -like "$_=*" }) }
    $salida += @(
        "DB_ENGINE=sqlite", "SQLITE_NAME=db_mini.sqlite3",
        "CLOUD_PROVIDER=deepseek", "CLOUD_API_BASE=https://api.deepseek.com",
        "CLOUD_MODEL=deepseek-chat", "CLOUD_VERIFICATION_MODEL=deepseek-chat", "CLOUD_LABEL=DeepSeek",
        "CLOUD_TOKENS_PER_MINUTE=0", "CLOUD_API_KEY=$clave"
    )
    [IO.File]::WriteAllLines($demo, $salida, (New-Object Text.UTF8Encoding $false))
    Write-Host "Creado .env.demo (DeepSeek, SQLite local). La clave no se muestra."
}

$env:SIMA_ENV_FILE = $demo
$env:SIMA_LECTOR = $Lector
py -3.14 manage.py migrate --noinput | Out-Null
py -3.14 manage.py shell -c @"
from django.contrib.auth.models import User
from learning.models import Profile
u, creado = User.objects.get_or_create(username='demo')
if creado:
    u.set_password('demo-mini'); u.save()
p, _ = Profile.objects.get_or_create(user=u)
p.credit_balance = max(p.credit_balance, 100); p.save()
"@
Write-Host ""
Write-Host "SIMA con el lector '$Lector' en http://127.0.0.1:$Puerto   usuario: demo   clave: demo-mini"
Write-Host "Ctrl+C para detener."
py -3.14 manage.py runserver "127.0.0.1:$Puerto" --noreload
