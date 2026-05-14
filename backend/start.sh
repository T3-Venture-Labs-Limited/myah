#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "$SCRIPT_DIR" || exit

# Add conditional Playwright browser installation
if [[ "${WEB_LOADER_ENGINE,,}" == "playwright" ]]; then
    if [[ -z "${PLAYWRIGHT_WS_URL}" ]]; then
        echo "Installing Playwright browsers..."
        playwright install chromium
        playwright install-deps chromium
    fi

    python -c "import nltk; nltk.download('punkt_tab')"
fi

# Phase B.2a: accept MYAH_SECRET_KEY_FILE alongside the legacy
# WEBUI_SECRET_KEY_FILE. Canonical name wins when both are set.
# Phase B.3b: default filename renamed to .myah_secret_key with a one-time
# on-disk migration from the legacy .webui_secret_key. Skipping this step
# would force every existing OSS install to regenerate the secret on first
# boot, invalidating all sessions.
if [ -n "${MYAH_SECRET_KEY_FILE}" ]; then
    KEY_FILE="${MYAH_SECRET_KEY_FILE}"
elif [ -n "${WEBUI_SECRET_KEY_FILE}" ]; then
    KEY_FILE="${WEBUI_SECRET_KEY_FILE}"
else
    KEY_FILE=".myah_secret_key"
    LEGACY_KEY_FILE=".webui_secret_key"
    if [ -e "$LEGACY_KEY_FILE" ] && [ ! -e "$KEY_FILE" ]; then
        if mv "$LEGACY_KEY_FILE" "$KEY_FILE" 2>/dev/null; then
            echo "Migrated legacy secret file: $LEGACY_KEY_FILE → $KEY_FILE"
        else
            echo "Warning: could not migrate legacy secret file $LEGACY_KEY_FILE"
        fi
    elif [ -e "$LEGACY_KEY_FILE" ] && [ -e "$KEY_FILE" ]; then
        echo "Warning: both $LEGACY_KEY_FILE and $KEY_FILE exist; using $KEY_FILE."
    fi
fi

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
if test "$MYAH_SECRET_KEY $WEBUI_SECRET_KEY $WEBUI_JWT_SECRET_KEY" = "  "; then
  echo "Loading MYAH_SECRET_KEY from file, not provided as an environment variable."

  if ! [ -e "$KEY_FILE" ]; then
    echo "Generating MYAH_SECRET_KEY"
    # Generate a random value to use as a MYAH_SECRET_KEY in case the user didn't provide one.
    echo $(head -c 12 /dev/random | base64) > "$KEY_FILE"
  fi

  echo "Loading MYAH_SECRET_KEY from $KEY_FILE"
  MYAH_SECRET_KEY=$(cat "$KEY_FILE")
  # Legacy back-compat: code that bypasses env.py still reads WEBUI_SECRET_KEY.
  WEBUI_SECRET_KEY="$MYAH_SECRET_KEY"
fi

if [[ "${USE_OLLAMA_DOCKER,,}" == "true" ]]; then
    echo "USE_OLLAMA is set to true, starting ollama serve."
    ollama serve &
fi

if [[ "${USE_CUDA_DOCKER,,}" == "true" ]]; then
  echo "CUDA is enabled, appending LD_LIBRARY_PATH to include torch/cudnn & cublas libraries."
  export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/lib/python3.11/site-packages/torch/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib"
fi

# Check if SPACE_ID is set, if so, configure for space
if [ -n "$SPACE_ID" ]; then
  echo "Configuring for HuggingFace Space deployment"
  if [ -n "$ADMIN_USER_EMAIL" ] && [ -n "$ADMIN_USER_PASSWORD" ]; then
    echo "Admin user configured, creating"
    MYAH_SECRET_KEY="$MYAH_SECRET_KEY" WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" uvicorn myah.main:app --host "$HOST" --port "$PORT" --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" &
    myah_pid=$!
    echo "Waiting for Myah to start..."
    while ! curl -s "http://localhost:${PORT}/health" > /dev/null; do
      sleep 1
    done
    echo "Creating admin user..."
    curl \
      -X POST "http://localhost:${PORT}/api/v1/auths/signup" \
      -H "accept: application/json" \
      -H "Content-Type: application/json" \
      -d "{ \"email\": \"${ADMIN_USER_EMAIL}\", \"password\": \"${ADMIN_USER_PASSWORD}\", \"name\": \"Admin\" }"
    echo "Shutting down Myah..."
    kill $myah_pid
  fi

  export WEBUI_URL=${SPACE_HOST}
fi

PYTHON_CMD=$(command -v python3 || command -v python)
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

# If script is called with arguments, use them; otherwise use default workers
if [ "$#" -gt 0 ]; then
    ARGS=("$@")
else
    ARGS=(--workers "$UVICORN_WORKERS")
fi

# Run uvicorn
MYAH_SECRET_KEY="$MYAH_SECRET_KEY" WEBUI_SECRET_KEY="$WEBUI_SECRET_KEY" exec "$PYTHON_CMD" -m uvicorn myah.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
    "${ARGS[@]}"