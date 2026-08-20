# FM4 Top 40 Downloader

A self-hosted web app that discovers the weekly [FM4 Top 40](https://fm4.orf.at/)
charts, shows the songs with their chart movement, finds the matching videos on
YouTube, and downloads them as audio files with `yt-dlp`.

## Features

- Discovers FM4 Top 40 charts automatically (tag page + story parsing) and keeps
  them up to date on a configurable schedule or with a manual refresh.
- Per-song detail view with up to 3 ranked YouTube candidates (official uploads
  and artist channels ranked first) and one-click download.
- Concurrent, resumable downloads with progress display; interrupted downloads
  are reconciled on restart.
- SQLite persistence, no external services. Everything runs on one machine
  (tested on a Raspberry Pi).
- Vue 3 single-page frontend compiled into the backend and served by FastAPI —
  no Node.js required at runtime.

## Requirements

- Python 3.11+
- `yt-dlp` (and `ffmpeg` for audio extraction) on the `PATH` or configured via
  `YTDLP_PATH`
- A free [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
  key for video search. The app caches search results aggressively to stay far
  below the default 10,000 daily quota units.

## Quick start (development)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # set YOUTUBE_API_KEY
.venv/bin/python -m uvicorn backend.app.main:app --reload
```

Open http://localhost:8000. On the first visit, press **Refresh charts** to
import the latest FM4 Top 40.

To rebuild the frontend after changing the Vue sources:

```bash
cd frontend
npm install
npm run build               # writes into backend/static
```

## Configuration

All settings come from environment variables or a `.env` file in the working
directory (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Bind address. `0.0.0.0` exposes the app on your LAN. |
| `DATA_DIR` | `./data` | Holds the SQLite database. |
| `DATABASE_URL` | `<DATA_DIR>/fm4top40.db` | Override the SQLite URL if needed. |
| `FM4_POLL_INTERVAL` | `6h` | How often to check for new charts (`30m`, `6h`, `1d`, or seconds). |
| `FM4_TAG_URL` | FM4 tag page | Page that links to chart articles. |
| `FM4_MAX_CHARTS_PER_RUN` | `16` | Chart articles to inspect per refresh. |
| `YOUTUBE_API_KEY` | *(required)* | YouTube Data API v3 key. |
| `YOUTUBE_MAX_RESULTS` | `10` | Raw search results fetched per song. |
| `YOUTUBE_CANDIDATES` | `3` | Ranked candidates shown per song. |
| `DOWNLOAD_DIRECTORY` | `./music` | Where downloads are stored. |
| `YTDLP_PATH` | `yt-dlp` | Path to the yt-dlp executable. |
| `YTDLP_FORMAT` | `bestaudio/best` | yt-dlp format selector. |
| `YTDLP_EXTRACT_AUDIO` | `true` | Extract audio (needs `ffmpeg`). |
| `YTDLP_AUDIO_FORMAT` | `mp3` | Target audio format. |
| `YTDLP_AUDIO_QUALITY` | `0` | Audio quality (`0` = best). |
| `DOWNLOAD_CONCURRENCY` | `1` | Parallel downloads. |
| `LOG_LEVEL` | `INFO` | Log verbosity. |

## Deployment (Raspberry Pi / systemd)

The repo ships a systemd unit and installer in `deploy/`:

```bash
./deploy/install.sh --user root
```

This creates a dedicated `fm4top40` system user, installs the app under
`/opt/fm4-top40`, prepares the virtualenv and built frontend, reads config from
`/etc/fm4-top40.env`, and enables `fm4-top40.service`. The service listens on
`0.0.0.0:8000`; point your browser (or a reverse proxy) at the Pi's address.

Useful commands:

```bash
systemctl status fm4-top40
journalctl -u fm4-top40 -f
sudo systemctl edit fm4-top40   # override e.g. EnvironmentFile
```

## API overview

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Liveness probe. |
| `GET` | `/api/charts` | List charts (newest first) with download counts. |
| `GET` | `/api/charts/{id}` | Chart detail with entries and download status. |
| `POST` | `/api/charts/refresh` | Run chart discovery/import now. |
| `GET` | `/api/songs/{id}` | Song detail. |
| `GET` | `/api/songs/{id}/youtube` | Cached YouTube candidates. |
| `POST` | `/api/songs/{id}/youtube/search` | Search YouTube (`?refresh=true` to force). |
| `POST` | `/api/songs/{id}/download` | Queue a download (`{"youtube_result_id": N}`). |
| `GET` | `/api/downloads` | List all downloads. |
| `GET` | `/api/downloads/{id}` | Download status and progress. |

## Tests

```bash
. .venv/bin/python -m pytest backend/tests        # backend (42 tests)
cd frontend && npm test                            # frontend (21 tests)
```

The test suite uses a throwaway SQLite database and fakes the YouTube API and
the `yt-dlp` subprocess, so no network or API key is needed.

## Project layout

```
backend/app/            FastAPI app (API, services, scheduler)
backend/tests/          pytest suite + FM4 fixture
frontend/               Vue 3 SPA, built into backend/static
deploy/                 systemd unit + installer
.env.example            configuration template
```

## Troubleshooting

- **"YOUTUBE_API_KEY is not configured"**: set the key in `.env` (or
  `/etc/fm4-top40.env` when deployed) and restart.
- **Downloads fail / no audio**: make sure `ffmpeg` is installed; audio
  extraction without it fails. Check `journalctl -u fm4-top40`.
- **No charts found**: the app relies on the current FM4 tag page layout. If
  ORF changes it, chart discovery may return nothing; run
  `POST /api/charts/refresh` and check the logs.
- **503 on download**: the download manager is only available once the app has
  finished starting; wait a moment and retry.