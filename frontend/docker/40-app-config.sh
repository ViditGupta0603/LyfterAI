#!/bin/sh
# Writes the runtime config read by index.html, so one image works against any backend URL.
set -eu
api_url="${API_URL:-http://localhost:8000}"
escaped=$(printf '%s' "$api_url" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf 'window.__APP_CONFIG__ = { API_URL: "%s" };\n' "$escaped" > /usr/share/nginx/html/config.js
echo "app config: API_URL=$api_url"
