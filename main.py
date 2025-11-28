from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import create_engine, Column, DateTime, String, Integer, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
from typing import List, Dict, Any, Optional
import json
import threading
import time
from functools import lru_cache

app = FastAPI(title="ChuntFM Schedule API", version="0.1.0")

DATABASE_URL = "sqlite:///./schedule.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

cache_lock = threading.Lock()
cache_data = {}
cache_last_updated = None

class Schedule(Base):
    __tablename__ = "schedule"
    
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
    
    if cache_last_updated is None:
        return False
    
    last_db_update = db.execute(
        text("SELECT MAX(COALESCE(updated_at, created_at, datetime('now'))) FROM schedule")
    ).scalar()
    
    if last_db_update and last_db_update > cache_last_updated:
        return False
    
    return True

def refresh_cache(db: Session):
    global cache_data, cache_last_updated
    
    with cache_lock:
        now = datetime.now()
        
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
        
        cache_last_updated = datetime.now()

def get_cached_data(key: str, db: Session):
    if not check_cache_validity(db):
        refresh_cache(db)
    
    return cache_data.get(key, [])

@app.get("/schedule/previous")
async def get_previous_schedule(db: Session = Depends(get_db)):
    return get_cached_data("previous", db)

@app.get("/schedule/upnext")
async def get_upnext_schedule(db: Session = Depends(get_db)):
    return get_cached_data("upnext", db)

@app.get("/schedule/now")
async def get_current_schedule(db: Session = Depends(get_db)):
    return get_cached_data("now", db)

@app.get("/schedule/when")
async def search_schedule(
    title: Optional[str] = Query(None),
    description: Optional[str] = Query(None),
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

@app.get("/schedule/what")
async def get_schedule_at_time(
    time: str = Query(..., description="ISO 8601 timestamp"),
    db: Session = Depends(get_db)
):
    try:
        target_time = datetime.fromisoformat(time.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use ISO 8601 format")
    
    all_items = get_cached_data("all", db)
    results = []
    
    for item in all_items:
        start_time = datetime.fromisoformat(item["start"].replace('Z', '+00:00'))
        stop_time = datetime.fromisoformat(item["stop"].replace('Z', '+00:00'))
        
        if start_time <= target_time <= stop_time:
            results.append(item)
    
    return results

@app.post("/admin/refresh-cache")
async def manual_cache_refresh(db: Session = Depends(get_db)):
    refresh_cache(db)
    return {"message": "Cache refreshed successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)