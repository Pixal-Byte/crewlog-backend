#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
TOKEN_ONE="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
TOKEN_TWO="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"

{
    echo "CREWLOG_TOKEN_KEY=$TOKEN_ONE"
    echo "CREWLOG_IP_KEY=$TOKEN_TWO"
} > "$SCRIPT_DIR/.env"

chmod 600 "$SCRIPT_DIR/.env"
echo "=== Built .env ==="