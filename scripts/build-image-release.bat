@echo off
setlocal EnableDelayedExpansion

:: ============================================
:: Nanobot WebUI - Docker Image Build Script
:: ============================================

:: Default values
set "IMAGE_TAG=nanobot-webui:local"
set "RELEASE_DIR=deployment\release"
set "ARCHIVE_NAME=nanobot-webui-local.tar.gz"
set "PUBLISHED_PORT=18780"
set "CONTAINER_NAME=nanobot-webui"
set "TIMEZONE=Asia/Shanghai"
set "WEBUI_LOG_LEVEL=INFO"
set "WEBUI_ONLY=true"
set "WEBUI_AUTH_DISABLED=true"
set "INSTANCE_ROOT=./data"
set "SKILLS_ROOT=./skills"
set "SKIP_BUILD=0"

:: Parse arguments
:parse_args
if "%~1"=="" goto :end_parse
if /i "%~1"=="--image-tag" (
    set "IMAGE_TAG=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--release-dir" (
    set "RELEASE_DIR=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--archive-name" (
    set "ARCHIVE_NAME=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--skip-build" (
    set "SKIP_BUILD=1"
    shift
    goto :parse_args
)
if /i "%~1"=="-h" goto :show_help
if /i "%~1"=="--help" goto :show_help
echo Unknown option: %~1
goto :show_help

:end_parse

:: Get script directory
set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%.."
cd /d "%ROOT_DIR%"
set "ROOT_DIR=%cd%"

:: Check Docker
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker not found. Please install Docker Desktop.
    exit /b 1
)

:: Check if WSL is available for Docker
wsl --list >nul 2>&1
if errorlevel 1 (
    echo [ERROR] WSL not found. Docker requires WSL on Windows.
    exit /b 1
)

:: Build image
if "%SKIP_BUILD%"=="0" (
    echo [release] Building image %IMAGE_TAG%...
    echo [release] This may take 10-20 minutes...
    wsl -d Ubuntu bash -c "cd /mnt/e/workspace/nanobot-webui && sudo docker build -t %IMAGE_TAG% ."
    if errorlevel 1 (
        echo [ERROR] Docker build failed.
        exit /b 1
    )
) else (
    echo [release] Skipping build, exporting existing image %IMAGE_TAG%
)

:: Prepare release directory
set "ABS_RELEASE_DIR=%ROOT_DIR%\%RELEASE_DIR%"
echo [release] Preparing %ABS_RELEASE_DIR%...

if exist "%ABS_RELEASE_DIR%" rmdir /s /q "%ABS_RELEASE_DIR%"
mkdir "%ABS_RELEASE_DIR%"

:: Copy release files
set "SOURCE_RELEASE_DIR=%ROOT_DIR%\deployment\release"
for %%f in (docker-compose.yml .env.example config.template.json config.json README.md DEPLOYMENT-GUIDE.md) do (
    if exist "%SOURCE_RELEASE_DIR%\%%f" (
        copy "%SOURCE_RELEASE_DIR%\%%f" "%ABS_RELEASE_DIR%\" >nul
    ) else (
        echo [WARNING] Missing release template: %%f
    )
)

:: Export image
echo [release] Exporting image archive...
echo [release] This may take a few minutes...
wsl -d Ubuntu bash -c "cd /mnt/e/workspace/nanobot-webui && sudo docker save %IMAGE_TAG% | gzip > %RELEASE_DIR%/%ARCHIVE_NAME%"

if errorlevel 1 (
    echo [ERROR] Failed to export image.
    exit /b 1
)

:: Show result
echo.
echo [release] ========================================
echo [release] Build completed successfully!
echo [release] ========================================
echo.
echo [release] Generated files:
dir /b "%ABS_RELEASE_DIR%"
echo.
echo [release] Output directory: %ABS_RELEASE_DIR%
echo [release] Image archive: %ARCHIVE_NAME%
echo.
echo [release] Next steps:
echo [release] 1. Upload the release folder to your server
echo [release] 2. Run: docker load ^< %ARCHIVE_NAME%
echo [release] 3. Run: docker-compose up -d
echo.

exit /b 0

:show_help
echo.
echo Usage: build-image-release.bat [options]
echo.
echo Build the local Docker image and prepare an intranet delivery directory.
echo.
echo Options:
echo   --image-tag ^<tag^>        Docker image tag to build/export (default: nanobot-webui:local)
echo   --release-dir ^<dir^>      Output directory for release files (default: deployment\release)
echo   --archive-name ^<name^>    Image archive filename (default: nanobot-webui-local.tar.gz)
echo   --skip-build             Skip docker build and export the existing image only
echo   -h, --help               Show this help text
echo.
exit /b 0
