from fastapi import FastAPI, Depends, HTTPException, Query, Header, APIRouter
from sqlalchemy import create_engine, Column, DateTime, String, Integer, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime, timezone
from dateutil import parser
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import json
import threading
import os

try:
    from config import *
except ImportError:
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./schedule.db")
    TABLE_NAME = os.getenv("TABLE_NAME", "schedule")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    API_TITLE = os.getenv("API_TITLE", "ChuntFM Schedule API")
    API_VERSION = os.getenv("API_VERSION", "0.1.0")
    API_PREFIX = os.getenv("API_PREFIX", "/schedule")
    ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "change-this-api-key")
    CACHE_ENABLED = os.getenv("CACHE_ENABLED", "True").lower() == "true"
    CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

app = FastAPI(
    title=API_TITLE, 
    version=API_VERSION,
    docs_url=f"{API_PREFIX}/docs" if API_PREFIX else "/docs",
    redoc_url=f"{API_PREFIX}/redoc" if API_PREFIX else "/redoc",
    openapi_url=f"{API_PREFIX}/openapi.json" if API_PREFIX else "/openapi.json"
)
router = APIRouter()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Response models and examples
class CacheRefreshResponse(BaseModel):
    message: str = Field(description="Status message")

# Common response examples
SCHEDULE_EXAMPLES = {
    "past": {
        "start": "2023-01-01T09:00:00+00:00",
        "stop": "2023-01-01T10:00:00+00:00",
        "title": "Morning News",
        "description": "Daily news briefing"
    },
    "future": {
        "start": "2023-01-01T14:00:00+00:00",
        "stop": "2023-01-01T15:00:00+00:00",
        "title": "Afternoon Show", 
        "description": "Weekly talk show"
    },
    "current": {
        "start": "2023-01-01T12:00:00+00:00",
        "stop": "2023-01-01T13:00:00+00:00",
        "title": "Lunch Hour Music",
        "description": "Relaxing music during lunch"
    },
    "search": {
        "start": "2023-01-01T18:00:00+00:00", 
        "stop": "2023-01-01T19:00:00+00:00",
        "title": "News Hour",
        "description": "Evening news and current affairs"
    },
    "time_query": {
        "start": "2023-01-01T10:30:00+00:00",
        "stop": "2023-01-01T11:30:00+00:00", 
        "title": "Weekend Special",
        "description": "Special weekend programming"
    }
}

def create_schedule_responses(example_key: str):
    """Create standard schedule endpoint response documentation"""
    return {
        200: {
            "description": "List of schedule entries",
            "content": {
                "application/json": {
                    "example": [SCHEDULE_EXAMPLES[example_key]]
                }
            }
        }
    }

cache_lock = threading.Lock()
cache_data = {}
cache_last_updated = None

class Schedule(Base):
    __tablename__ = TABLE_NAME
    __table_args__ = {'extend_existing': True}
    
    id = Column(Integer, primary_key=True, index=True)
    start = Column(DateTime(timezone=True), nullable=False)
    stop = Column(DateTime(timezone=True), nullable=False)
    data = Column(String, nullable=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_parsed_data(schedule_item):
    try:
        parsed_data = json.loads(schedule_item.data)
    except json.JSONDecodeError:
        parsed_data = {"raw_data": schedule_item.data}
    
    return {
        "id": schedule_item.id,
        "start": schedule_item.start.isoformat(),
        "stop": schedule_item.stop.isoformat(),
        **parsed_data
    }

def check_cache_validity(db: Session):
    global cache_last_updated
    
    if not CACHE_ENABLED:
        return False
        
    if cache_last_updated is None:
        return False
    
    # Check TTL
    if CACHE_TTL > 0:
        cache_age = (datetime.now(timezone.utc) - cache_last_updated).total_seconds()
        if cache_age > CACHE_TTL:
            return False
    
    # Check database timestamps if available
    try:
        last_db_update = db.execute(
            text(f"SELECT MAX(COALESCE(updated_at, created_at, datetime('now'))) FROM {TABLE_NAME}")
        ).scalar()
        
        if last_db_update and last_db_update > cache_last_updated:
            return False
    except:
        # If timestamp columns don't exist, rely on TTL only
        pass
    
    return True

def refresh_cache(db: Session):
    global cache_data, cache_last_updated
    
    with cache_lock:
        now = datetime.now(timezone.utc)
        
        all_items = db.query(Schedule).all()
        
        cache_data = {
            "previous": [],
            "upnext": [],
            "now": [],
            "all": []
        }
        
        for item in all_items:
            parsed_item = get_parsed_data(item)
            cache_data["all"].append(parsed_item)
            
            if item.stop < now:
                cache_data["previous"].append(parsed_item)
            elif item.start > now:
                cache_data["upnext"].append(parsed_item)
            elif item.start <= now <= item.stop:
                cache_data["now"].append(parsed_item)
        
        cache_last_updated = datetime.now(timezone.utc)

def get_cached_data(key: str, db: Session):
    try:
        if CACHE_ENABLED and check_cache_validity(db):
            return cache_data.get(key, [])
        
        # Cache disabled or invalid - query database directly
        now = datetime.now(timezone.utc)
        all_items = db.query(Schedule).all()
        
        results = []
        for item in all_items:
            try:
                parsed_item = get_parsed_data(item)
                
                if key == "previous" and item.stop < now:
                    results.append(parsed_item)
                elif key == "upnext" and item.start > now:
                    results.append(parsed_item)
                elif key == "now" and item.start <= now <= item.stop:
                    results.append(parsed_item)
                elif key == "all":
                    results.append(parsed_item)
            except Exception:
                # Skip malformed records
                continue
        
        # Refresh cache if enabled but invalid
        if CACHE_ENABLED and not check_cache_validity(db):
            try:
                refresh_cache(db)
            except Exception:
                # Cache refresh failed, continue with direct query results
                pass
        
        return results
    except Exception:
        # Return empty list if database query fails completely
        return []

@router.get(
    "/",
    response_model=List[Dict[str, Any]],
    summary="Get all schedule entries",
    description="Returns all schedule entries regardless of time.",
    responses=create_schedule_responses("current")
)
async def get_all_schedule(db: Session = Depends(get_db)):
    return get_cached_data("all", db)

@router.get(
    "/previous",
    response_model=List[Dict[str, Any]],
    summary="Get past schedule entries",
    description="Returns all schedule entries that have ended (stop time is in the past).",
    responses=create_schedule_responses("past")
)
async def get_previous_schedule(db: Session = Depends(get_db)):
    return get_cached_data("previous", db)

@router.get(
    "/upnext",
    response_model=List[Dict[str, Any]],
    summary="Get upcoming schedule entries", 
    description="Returns all schedule entries that haven't started yet (start time is in the future).",
    responses=create_schedule_responses("future")
)
async def get_upnext_schedule(db: Session = Depends(get_db)):
    return get_cached_data("upnext", db)

@router.get(
    "/now",
    response_model=List[Dict[str, Any]],
    summary="Get currently active schedule entries",
    description="Returns all schedule entries that are currently active (current time is between start and stop times).",
    responses=create_schedule_responses("current")
)
async def get_current_schedule(db: Session = Depends(get_db)):
    return get_cached_data("now", db)

@router.get(
    "/when",
    response_model=List[Dict[str, Any]],
    summary="Search schedule entries by content",
    description="Search for schedule entries by title or description. At least one search parameter must be provided.",
    responses={
        **create_schedule_responses("search"),
        400: {
            "description": "Bad Request - No search parameters provided",
            "content": {
                "application/json": {
                    "example": {"detail": "Either title or description must be provided"}
                }
            }
        }
    }
)
async def search_schedule(
    title: Optional[str] = Query(None, description="Search in show titles"),
    description: Optional[str] = Query(None, description="Search in show descriptions"),
    db: Session = Depends(get_db)
):
    if not title and not description:
        raise HTTPException(status_code=400, detail="Either title or description must be provided")
    
    all_items = get_cached_data("all", db)
    results = []
    
    for item in all_items:
        match = False
        
        if title and "title" in item:
            if title.lower() in str(item["title"]).lower():
                match = True
        
        if description and "description" in item:
            if description.lower() in str(item["description"]).lower():
                match = True
        
        if match:
            results.append(item)
    
    return results

def parse_timestamp_lenient(time_str: str) -> tuple[datetime, datetime]:
    """Parse timestamp with various formats, returning (start_time, end_time) for range queries"""
    try:
        # Try ISO format first
        if 'T' in time_str or '+' in time_str or 'Z' in time_str:
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return (dt, dt)
        
        # Use dateutil for flexible parsing
        parsed = parser.parse(time_str)
        
        # If no timezone info, assume UTC
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        
        # If it looks like just a date (no time component), make it a day range
        if time_str.count(':') == 0 and ('T' not in time_str):
            # Date only - return full day range
            start_of_day = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            return (start_of_day, end_of_day)
        else:
            # Specific time - return exact moment
            return (parsed, parsed)
            
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, 
            detail="Invalid time format. Examples: '2023-01-01', '2023-01-01T10:00:00', '2023-01-01 10:00'"
        )

@router.get(
    "/what",
    response_model=List[Dict[str, Any]], 
    summary="Get schedule entries for specific time or date",
    description="Returns schedule entries active at a specific time or during an entire date. Supports flexible time parsing.",
    responses={
        **create_schedule_responses("time_query"),
        400: {
            "description": "Bad Request - Invalid time format",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid time format. Examples: '2023-01-01', '2023-01-01T10:00:00', '2023-01-01 10:00'"}
                }
            }
        }
    }
)
async def get_schedule_at_time(
    time: str = Query(
        ..., 
        description="Timestamp or date. Date-only queries (e.g., '2023-01-01') return all shows for that entire day. Specific times (e.g., '2023-01-01T10:00:00') return shows active at that exact moment.",
        examples=["2023-01-01", "2023-01-01T10:00:00", "2023-01-01 10:00"]
    ),
    db: Session = Depends(get_db)
):
    try:
        query_start, query_end = parse_timestamp_lenient(time)
        
        all_items = get_cached_data("all", db)
        results = []
        
        for item in all_items:
            try:
                start_time = datetime.fromisoformat(item["start"].replace('Z', '+00:00'))
                stop_time = datetime.fromisoformat(item["stop"].replace('Z', '+00:00'))
                
                # Check if show overlaps with query time range
                # Show overlaps if: show_start <= query_end AND show_end >= query_start
                if start_time <= query_end and stop_time >= query_start:
                    results.append(item)
            except Exception:
                # Skip malformed timestamps in data
                continue
        
        return results
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post(
    "/admin/refresh-cache",
    response_model=CacheRefreshResponse,
    summary="Manually refresh cache",
    description="Manually triggers a cache refresh. Requires admin API key in X-API-Key header.",
    responses={
        200: {
            "description": "Cache refresh successful",
            "content": {
                "application/json": {
                    "example": {"message": "Cache refreshed successfully"}
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid API key",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid API key"}
                }
            }
        }
    }
)
async def manual_cache_refresh(
    api_key: str = Header(..., alias="X-API-Key", description="Admin API key for authentication"),
    db: Session = Depends(get_db)
):
    if api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if not CACHE_ENABLED:
        return {"message": "Cache is disabled"}
    
    refresh_cache(db)
    return {"message": "Cache refreshed successfully"}

# Mount the router
app.include_router(router, prefix=API_PREFIX)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)