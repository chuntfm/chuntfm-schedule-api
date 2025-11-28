# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Run the API:**
```bash
python main.py
```

**Install dependencies:**
```bash
pip install -r requirements.txt
```

## Architecture Overview

This is a FastAPI-based read-only schedule API with in-memory caching. The application consists of:

**Single-file application** (`main.py`) containing:
- SQLAlchemy model for `schedule` table (timezone-aware timestamps, JSON data field)
- In-memory cache with thread-safe refresh mechanism
- Five REST endpoints for schedule queries
- Database session management with dependency injection

**Caching Strategy:**
- Pre-computed cache for time-based queries (`previous`, `upnext`, `now`) 
- Cache invalidation based on database timestamp detection
- Thread-safe cache updates using locks
- Manual refresh endpoint for external trigger integration

**Database Design:**
- Database-agnostic SQLAlchemy setup (defaults to SQLite)
- Schedule entries with `start`/`stop` timezone-aware timestamps
- JSON data field parsed and merged into API responses
- Supports external cache refresh triggers via timestamp columns

**API Endpoints:**
- Time-based: `/schedule/previous`, `/schedule/upnext`, `/schedule/now`
- Search: `/schedule/when` (text search), `/schedule/what` (time point query)
- Admin: `/admin/refresh-cache`

The application prioritizes simplicity (single file, minimal dependencies) and performance (precached responses, efficient time-based filtering).