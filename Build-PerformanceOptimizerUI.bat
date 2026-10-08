@echo off
rem Builds the Performance Improvements tab and installs it into your project.
rem Double-click this file, or drag your .uproject onto it.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-EditorPlugin.ps1" -PluginName PerformanceOptimizerUI %*
echo.
pause
