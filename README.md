# TG-Download-Bot

Telegram bot for magnet/AV download management via [Gopeed](https://github.com/GopeedLab/gopeed) with AI classification, poster fetching, and movie search.

## Workflow

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#1a73e8"
    primaryTextColor: "#fff"
    lineColor: "#5f6368"
    secondaryColor: "#e8f0fe"
    tertiaryColor: "#f8f9fa"
---
flowchart TD
    U([👤 User])
    C{Classify Input}
    HG([HGME Search])
    AV([Sukebei Search])
    GP[[Gopeed Downloader]]
    CR[Create Task<br/>POST /api/v1/tasks]
    MD[Wait Metadata<br/>GET /api/v1/tasks/{id}]
    FL[Filter Junk Files]
    PO[Poll Progress]
    AI{AI Analysis}
    TM[TMDB Poster]
    JB[Javbus Poster]
    PH([📸 Send Photo])
    ED([✅ Notify User])
    EF([❌ Show Error])

    U -->|sends message| C
    C -->|🔗 Magnet| GP
    C -->|🔞 AV Number| AV
    C -->|🎬 Movie/TV| HG
    HG -->|user selects| GP
    AV --> GP
    GP --> CR --> MD --> FL --> PO
    PO -->|running| PO
    PO -->|done| AI
    PO -->|error| EF
    AI -->|🎞 Movie| TM
    AI -->|🔞 AV| JB
    TM --> PH
    JB --> PH
    PO -->|done| ED

    style U fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#1565c0
    style C fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#e65100
    style GP fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c
    style AI fill:#fff8e1,stroke:#f9a825,color:#e65100
    style PH fill:#e3f2fd,stroke:#1565c0,color:#1565c0
    style ED fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    style EF fill:#ffebee,stroke:#c62828,color:#b71c1c
    style CR fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    style MD fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    style FL fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
    style PO fill:#f3e5f5,stroke:#7b1fa2,color:#4a148c
```

## Features

- **Input auto-classify** — magnet links, AV numbers, movie/TV show names
- **AI analysis** — OpenAI/Anthropic-compatible API to identify content type and clean name
- **Smart download** — auto-routes AV to AV directory, movies/TV to media directory
- **Poster fetching** — TMDB for movies, Javbus/AVMoo for AV
- **Progress tracking** — real-time download progress bar via inline message updates
- **HGME search** — Chinese-subtitle torrent search for movies/TV shows
- **Web config UI** — Flask-based configuration panel (port 9099)

## Requirements

- Python 3.9+
- [Gopeed](https://github.com/GopeedLab/gopeed) downloader running with API enabled
- Playwright (for HGME search)
- (Optional) AI API key for content classification

## Quick Start

### 1. Deploy Gopeed

[Gopeed](https://github.com/GopeedLab/gopeed) is a fast, modern download manager supporting HTTP, BitTorrent, Magnet, and ed2k.

```yaml
# docker-compose.yml for Gopeed
services:
  gopeed:
    image: liwei2633/gopeed:latest
    container_name: gopeed
    restart: unless-stopped
    network_mode: host
    environment:
      - GOPEED_USERNAME=admin
      - GOPEED_PASSWORD=your_password
      - GOPEED_APITOKEN=your_api_token
    volumes:
      - ./config:/app/storage
      - /path/to/downloads:/downloads
```

The bot connects to Gopeed via its REST API using `X-Api-Token` header:

| Endpoint | Description |
|---|---|
| `POST /api/v1/tasks` | Create download task |
| `GET /api/v1/tasks/{id}` | Get task status |
| `DELETE /api/v1/tasks/{id}` | Cancel task |

Set `GOPEED_URL` and `GOPEED_TOKEN` in config to match your Gopeed deployment.

### 2. Deploy Bot

```bash
cp config.env.example config.env
# Fill in your config
docker compose up -d
```

## Configuration

Set via `config.env` or environment variables:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `PROXY_URL` | HTTP proxy for Telegram API |
| `GOPEED_URL` | Gopeed REST API URL (default: `http://127.0.0.1:9999`) |
| `GOPEED_TOKEN` | Gopeed API Token (`X-Api-Token` header) |
| `AV_DEST` | Download directory for AV |
| `BT_DEST` | Download directory for movies/TV |
| `AI_API_URL` | OpenAI/Anthropic compatible API URL |
| `AI_API_KEY` | AI API key |
| `AI_MODEL` | AI model name |
| `HGME_ENABLED` | Enable HGME Chinese-sub search |
| `HGME_USERNAME` | HGME account username |
| `HGME_PASSWORD` | HGME account password |
