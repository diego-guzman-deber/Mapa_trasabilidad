@echo off
setlocal
title Permitir Mapa de Transitabilidad en Firewall

net session >nul 2>nul
if errorlevel 1 (
  echo Este archivo debe ejecutarse como Administrador.
  echo.
  echo Clic derecho sobre permitir_firewall_windows.bat
  echo y elige "Ejecutar como administrador".
  echo.
  pause
  exit /b 1
)

netsh advfirewall firewall add rule name="Mapa Transitabilidad Puerto 8000" dir=in action=allow protocol=TCP localport=8000 profile=any
netsh advfirewall firewall add rule name="Mapa Transitabilidad Puerto 8001-8010" dir=in action=allow protocol=TCP localport=8001-8010 profile=any

echo.
echo Reglas de firewall creadas para redes privadas, dominio y publicas.
echo.
pause
