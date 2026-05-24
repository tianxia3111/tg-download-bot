# TG-Download-Bot

Telegram bot for magnet/AV download management via [Gopeed](https://github.com/GopeedLab/gopeed) with AI classification, poster fetching, and movie search.

## Workflow

```mermaid
flowchart TD
    User -->|sends text| classify
    
    subgraph classify [Input Classification]
        direction LR
        magnet[Magnet Link] --> download
        av[AV Number] --> search_sukebei[Sukebei Search]
        search_sukebei --> download
        movie[Movie/TV Name] --> hgme[HGME Search]
        hgme -->|user selects| download
    end
    
    subgraph download [Download Pipeline]
        direction TB
        submit[Submit to Gopeed API] --> metadata[Wait for Metadata]
        metadata --> filter[Filter Junk Files]
        filter --> poll[Poll Progress]
    end
    
    subgraph ai [AI Analysis]
        poster[Fetch Poster<br/>TMDB / Javbus] --> send[Send Photo to Telegram]
    end
    
    download --> ai
    poll -->|complete| notify[Notify User]

    style User fill:#e1f5fe
    style notify fill:#c8e6c9
    style send fill:#fff3e0
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
