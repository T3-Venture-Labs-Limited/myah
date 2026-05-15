:: This method is not recommended, and we recommend you use the `start.sh` file with WSL instead.
@echo off
SETLOCAL ENABLEDELAYEDEXPANSION

:: Get the directory of the current script
SET "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%" || exit /b

:: Add conditional Playwright browser installation
IF /I "%WEB_LOADER_ENGINE%" == "playwright" (
    IF "%PLAYWRIGHT_WS_URL%" == "" (
        echo Installing Playwright browsers...
        playwright install chromium
        playwright install-deps chromium
    )

    python -c "import nltk; nltk.download('punkt_tab')"
)

:: Phase B.2a: accept MYAH_SECRET_KEY_FILE alongside the legacy
:: WEBUI_SECRET_KEY_FILE. Canonical name wins when both are set.
:: Phase B.3b: default filename renamed to .myah_secret_key with a one-time
:: on-disk migration from the legacy .webui_secret_key. Skipping this step
:: would force every existing OSS install to regenerate the secret on first
:: boot, invalidating all sessions.
SET "KEY_FILE=.myah_secret_key"
SET "LEGACY_KEY_FILE=.webui_secret_key"
IF EXIST "%LEGACY_KEY_FILE%" (
    IF NOT EXIST "%KEY_FILE%" (
        MOVE /Y "%LEGACY_KEY_FILE%" "%KEY_FILE%" >nul 2>&1 && (
            echo Migrated legacy secret file: %LEGACY_KEY_FILE% to %KEY_FILE%
        ) || (
            echo Warning: could not migrate legacy secret file %LEGACY_KEY_FILE%
        )
    ) ELSE (
        echo Warning: both %LEGACY_KEY_FILE% and %KEY_FILE% exist; using %KEY_FILE%.
    )
)
IF NOT "%WEBUI_SECRET_KEY_FILE%" == "" (
    SET "KEY_FILE=%WEBUI_SECRET_KEY_FILE%"
)
IF NOT "%MYAH_SECRET_KEY_FILE%" == "" (
    SET "KEY_FILE=%MYAH_SECRET_KEY_FILE%"
)

IF "%PORT%"=="" SET PORT=8080
IF "%HOST%"=="" SET HOST=0.0.0.0
IF "%FORWARDED_ALLOW_IPS%"=="" SET "FORWARDED_ALLOW_IPS=*"
SET "MYAH_SECRET_KEY=%MYAH_SECRET_KEY%"
SET "WEBUI_SECRET_KEY=%WEBUI_SECRET_KEY%"
SET "WEBUI_JWT_SECRET_KEY=%WEBUI_JWT_SECRET_KEY%"

:: Check if MYAH_SECRET_KEY, WEBUI_SECRET_KEY and WEBUI_JWT_SECRET_KEY are not set
IF "%MYAH_SECRET_KEY% %WEBUI_SECRET_KEY% %WEBUI_JWT_SECRET_KEY%" == "  " (
    echo Loading MYAH_SECRET_KEY from file, not provided as an environment variable.

    IF NOT EXIST "%KEY_FILE%" (
        echo Generating MYAH_SECRET_KEY
        :: Generate a random value to use as a MYAH_SECRET_KEY in case the user didn't provide one
        SET /p MYAH_SECRET_KEY=<nul
        FOR /L %%i IN (1,1,12) DO SET /p MYAH_SECRET_KEY=<!random!>>%KEY_FILE%
        echo MYAH_SECRET_KEY generated
    )

    echo Loading MYAH_SECRET_KEY from %KEY_FILE%
    SET /p MYAH_SECRET_KEY=<%KEY_FILE%
    :: Legacy back-compat: code that bypasses env.py still reads WEBUI_SECRET_KEY.
    SET "WEBUI_SECRET_KEY=!MYAH_SECRET_KEY!"
)

:: Execute uvicorn
SET "MYAH_SECRET_KEY=%MYAH_SECRET_KEY%"
SET "WEBUI_SECRET_KEY=%WEBUI_SECRET_KEY%"
IF "%UVICORN_WORKERS%"=="" SET UVICORN_WORKERS=1
uvicorn myah.main:app --host "%HOST%" --port "%PORT%" --forwarded-allow-ips "%FORWARDED_ALLOW_IPS%" --workers %UVICORN_WORKERS% --ws auto
:: For ssl user uvicorn myah.main:app --host "%HOST%" --port "%PORT%" --forwarded-allow-ips '*' --ssl-keyfile "key.pem" --ssl-certfile "cert.pem" --ws auto
