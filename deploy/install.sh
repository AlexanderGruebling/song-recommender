#!/usr/bin/env bash
# Install the FM4 Top 40 Downloader as a systemd service.
#
# Usage: sudo ./deploy/install.sh [--user NAME]   (default: fm4top40)
#
# Requires: systemd, python3 (>= 3.11), and either yt-dlp+ffmpeg on the host
# or a configured YTDLP_PATH. Node.js is only needed to rebuild the frontend.
set -euo pipefail

APP_NAME="fm4-top40"
APP_DIR="/opt/fm4-top40"
ENV_FILE="/etc/${APP_NAME}.env"
SERVICE_DIR="/etc/systemd/system"
RUN_USER="fm4top40"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)
            RUN_USER="$2"
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if [[ "$(id -u)" -ne 0 ]]; then
    echo "run me as root (sudo)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo "==> Installing $APP_NAME to $APP_DIR (user: $RUN_USER)"
# Create the service user before anything is chowned to it.
if [[ "$RUN_USER" != "root" ]]; then
    id -u "$RUN_USER" &>/dev/null || useradd --system --user-group --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$RUN_USER"
fi
RUN_GROUP="$(id -gn "$RUN_USER")"
install -d -o "$RUN_USER" -g "$RUN_GROUP" "$APP_DIR"

# Python virtualenv + dependencies.
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

# Source tree (keep backend/static so no Node.js is needed). A local .env
# is excluded: the service reads its config from $ENV_FILE, and a stray .env
# in the working directory would silently override it.
rsync -a --delete --exclude=".venv" --exclude="data" --exclude="music" \
    --exclude="frontend/node_modules" --exclude=".git" --exclude=".env" \
    "$REPO_DIR/" "$APP_DIR/"

install -d -o "$RUN_USER" -g "$RUN_GROUP" "$APP_DIR/data" "$APP_DIR/music"

# Example config on first install; admin fills in YOUTUBE_API_KEY.
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$REPO_DIR/.env.example" "$ENV_FILE"
    # Point relative paths at the install directory.
    sed -i \
        -e "s#^DATA_DIR=.*#DATA_DIR=$APP_DIR/data#" \
        -e "s#^DOWNLOAD_DIRECTORY=.*#DOWNLOAD_DIRECTORY=$APP_DIR/music#" \
        "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    echo
    echo "==> Edit $ENV_FILE and set YOUTUBE_API_KEY, then restart the service:"
    echo "    systemctl restart $APP_NAME"
fi

# Install the unit with the chosen user/group substituted in.
sed -e "s#^User=.*#User=$RUN_USER#" -e "s#^Group=.*#Group=$RUN_GROUP#" \
    "$SCRIPT_DIR/${APP_NAME}.service" > "$SERVICE_DIR/${APP_NAME}.service"
systemctl daemon-reload
systemctl enable "$APP_NAME"
systemctl restart "$APP_NAME"

echo "==> Done. Status:"
systemctl --no-pager --full status "$APP_NAME" | head -n 10 || true
echo "==> Logs: journalctl -u $APP_NAME -f"