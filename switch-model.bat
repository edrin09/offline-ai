@echo off
setlocal
title llama.cpp Model Switcher (ik_llama)

:: ============================================================
:: All tunable values live in .env next to this file.
:: Change parameters in .env, not in this script.
:: NOTE: keep this file ASCII-only + CRLF. The console here is a
:: GBK (cp936) window, so non-ASCII text in a .bat breaks cmd
:: parsing. Chinese console output is log_filter.py's job.
:: ============================================================
set "ENV_FILE=%~dp0.env"
if not exist "%ENV_FILE%" (
  echo [error] config file not found: "%ENV_FILE%"
  echo         The .env in the repo root is the startup config and
  echo         must sit in the same directory as this .bat.
  pause
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%ENV_FILE%") do if not "%%~a"=="" set "%%a=%%b"

:: Full paths derived from .env
set "SERVER=%SERVER_DIR%\%SERVER_EXE%"

:: Config check: fail loudly if a key file is missing, instead of
:: opening a window that flashes by.
call :require "%PYTHON%" PYTHON || goto cfgfail
call :require "%SERVER%" SERVER || goto cfgfail
call :require "%LOG_FILTER%" LOG_FILTER || goto cfgfail

echo ============================================
echo   Model Switcher - ik_llama.cpp  (port %PORT%)
echo ============================================
echo   [1] Coder  - %MODEL_CODER%   (coding / agent / tool-calling, NO vision)
echo   [2] Office - %MODEL_OFFICE%   (+ %MMPROJ_OFFICE%, WITH vision)
echo ============================================
choice /c 12 /n /m "Select model [1/2]: "
if errorlevel 2 goto office
if errorlevel 1 goto coder

:coder
call :require "%MODELS_DIR%\%MODEL_CODER%" MODEL_CODER || goto cfgfail
call :freeport || goto end
start "ik-llama-coder" /D "%SERVER_DIR%" cmd /c "chcp 65001 >nul && "%PYTHON%" -u "%LOG_FILTER%" "%SERVER%" -m "%MODELS_DIR%\%MODEL_CODER%" --port %PORT% --host %HOST% --ctx-size %CTX_SIZE% --threads %THREADS% -b %BATCH% -ub %UBATCH% -fa %FLASH_ATTN% -ctk %CACHE_TYPE_K% -ctv %CACHE_TYPE_V% -cram %CRAM% --jinja --slot-save-path "%SLOTS_DIR%""
echo.
echo [Coder] starting... API: http://%HOST%:%PORT%/v1/chat/completions
goto end

:office
call :require "%MODELS_DIR%\%MODEL_OFFICE%" MODEL_OFFICE || goto cfgfail
call :require "%MODELS_DIR%\%MMPROJ_OFFICE%" MMPROJ_OFFICE || goto cfgfail
call :freeport || goto end
start "ik-llama-office" /D "%SERVER_DIR%" cmd /c "chcp 65001 >nul && "%PYTHON%" -u "%LOG_FILTER%" "%SERVER%" -m "%MODELS_DIR%\%MODEL_OFFICE%" --mmproj "%MODELS_DIR%\%MMPROJ_OFFICE%" --port %PORT% --host %HOST% --ctx-size %CTX_SIZE% --threads %THREADS% -b %BATCH% -ub %UBATCH% -fa %FLASH_ATTN% -ctk %CACHE_TYPE_K% -ctv %CACHE_TYPE_V% -cram %CRAM% --jinja --slot-save-path "%SLOTS_DIR%""
echo.
echo [Office-VL] starting... API: http://%HOST%:%PORT%/v1/chat/completions
goto end

:end
echo.
echo Window closes in 5 seconds...
timeout /t 5 >nul
goto :eof

:cfgfail
echo.
echo [error] .env is misconfigured, startup aborted.
echo         The line above names the missing key / file.
echo         If several keys are reported missing at once, .env probably has
echo         LF line endings: cmd for /f only reads CRLF. Re-save .env as
echo         UTF-8 (no BOM) + Windows (CRLF).
pause
exit /b 1

:: ============================================
:: Subroutine: check a file exists (%~1=path, %~2=.env key name)
:: ============================================
:require
if exist "%~1" exit /b 0
echo.
echo [error] file pointed to by .env key %~2 does not exist: "%~1"
exit /b 1

:: ============================================
:: Subroutine: make sure port %PORT% is free
:: (kill holders first, then start)
:: ============================================
:freeport
echo.
echo [port] freeing port %PORT% ...
taskkill /IM %SERVER_EXE% /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /c:":%PORT% " ^| findstr /c:"LISTENING"') do taskkill /PID %%p /F >nul 2>&1
set "WAIT=0"
:waitfree
netstat -ano | findstr /c:":%PORT% " | findstr /c:"LISTENING" >nul 2>&1
if errorlevel 1 goto portready
set /a WAIT+=1
if %WAIT% GEQ %PORT_WAIT_SEC% goto portfail
timeout /t 1 >nul
goto waitfree
:portfail
echo [port] ERROR: port %PORT% still occupied after %PORT_WAIT_SEC%s, aborting start.
exit /b 1
:portready
echo [port] port %PORT% is free, ready to start.
exit /b 0
