# Prepara la consola de PowerShell para la demo: todo en UTF-8.
# Uso (desde la raíz del proyecto, con punto y espacio para que aplique a la sesión actual):
#   . .\scripts\entorno-demo.ps1
#
# Motivo: el lote escribe en UTF-8, pero esta consola usa la página de códigos 936 (china)
# y muestra mal caracteres como "·", tildes o "ñ".

chcp 65001 > $null
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$OutputEncoding = $utf8

# Python: forzar UTF-8 en stdin/stdout/stderr también para Streamlit y subprocesos.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-Host "Consola en UTF-8 (página de códigos 65001). Prueba: · á é í ó ú ñ"
