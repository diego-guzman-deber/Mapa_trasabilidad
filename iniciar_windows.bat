@echo off
setlocal
title Mapa de Transitabilidad

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -u "%~dp0mantener_mapa.py"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo No se encontro Python 3 en Windows.
    echo.
    echo Instala Python desde https://www.python.org/downloads/windows/
    echo y marca la opcion "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
  )
  python -u "%~dp0mantener_mapa.py"
)

echo.
echo El lanzador se cerro.
echo Si viste un error arriba, mandame ese texto.
pause
