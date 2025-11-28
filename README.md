# ChuntFM Schedule API

FastAPI read-only API for schedule data with caching.

## Setup

```bash
pip install -r requirements.txt
cp config.py.example config.py  # Edit config.py for your environment
```

## Development

```bash
python main.py
```

## Production Deployment

```bash
# Using gunicorn
gunicorn -c gunicorn.conf.py main:app

# Using environment variables
DATABASE_URL=postgresql://user:pass@localhost/db gunicorn -c gunicorn.conf.py main:app

# Run on root path (for reverse proxy routing)
API_PREFIX="" gunicorn -c gunicorn.conf.py main:app

# Using Docker (example)
docker run -e DATABASE_URL=postgresql://... -p 8000:8000 your-image
```

## Database Schema

Table: `schedule`
- `id`: Integer primary key
- `start`: Timezone-aware timestamp
- `stop`: Timezone-aware timestamp  
- `data`: JSON string

## Endpoints

### Time-based Queries

- `GET /schedule/previous` - All entries with stop time in the past
- `GET /schedule/upnext` - All entries with start time in the future
- `GET /schedule/now` - All entries currently active (start <= now <= stop)

### Search Queries

- `GET /schedule/when?title=<text>&description=<text>` - Search by title or description (one required)
- `GET /schedule/what?time=<timestamp>` - Get entries for time/date range
  - Date only (`2023-01-01`): All shows during that entire day  
  - Specific time (`2023-01-01T10:00:00`): Shows active at exact moment

### Cache Management

- `POST /admin/refresh-cache` - Manually refresh cache

## Cache Refresh Triggers

To trigger cache refresh from database scripts:
1. Call `POST /admin/refresh-cache` endpoint
2. Ensure database has `updated_at` or `created_at` timestamp columns for automatic detection
3. Use database triggers to update timestamp columns on data changes

## Response Format

All endpoints return JSON arrays with items containing:
```json
{
  "id": 1,
  "start": "2023-01-01T10:00:00+00:00",
  "stop": "2023-01-01T11:00:00+00:00",
  "title": "Example",
  "description": "Example description"
}
```

Data field is parsed as JSON and merged into response.