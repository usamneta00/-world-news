import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import json
import re
import time
import threading
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import yt_dlp
import requests
from bs4 import BeautifulSoup
import hashlib
from urllib.parse import urljoin, urlparse, quote
import html
import numpy as np
from telethon import TelegramClient
from telethon.sessions import StringSession
import requests
import json
import re

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI App Setup
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

# Database setup - Use /data for Railway Volume persistence
import os
DATA_DIR = os.environ.get('DATA_DIR', '/data' if os.path.exists('/data') else '.')
DB_PATH = os.path.join(DATA_DIR, 'world_news.db')
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
logger.info(f"Using database at: {DB_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class NewsItem(Base):
    __tablename__ = "news"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    link = Column(String, unique=True)
    summary = Column(String)
    published = Column(DateTime)
    source = Column(String)
    image_url = Column(String, nullable=True)
    video_id = Column(String, nullable=True)  # YouTube video ID
    is_important = Column(Integer, default=0) # 1 if marked as important by Google/classification
    importance_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now) # Track when added to our DB

class ChannelLastVideo(Base):
    __tablename__ = "channel_last_video"
    id = Column(Integer, primary_key=True, index=True)
    channel_name = Column(String, unique=True)
    last_video_ids = Column(String)  # JSON array of last 5 video IDs
    last_video_published = Column(DateTime)  # Most recent video's publish date
    updated_at = Column(DateTime, default=datetime.now)

# Yemen News Tables
class YemenNewsItem(Base):
    __tablename__ = "yemen_news"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    link = Column(String, unique=True)
    summary = Column(String)
    published = Column(DateTime)
    source = Column(String)
    image_url = Column(String, nullable=True)
    video_id = Column(String, nullable=True)
    is_important = Column(Integer, default=0)
    importance_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now) # Track when added to our DB

class YemenChannelLastVideo(Base):
    __tablename__ = "yemen_channel_last_video"
    id = Column(Integer, primary_key=True, index=True)
    channel_name = Column(String, unique=True)
    last_video_ids = Column(String)  # JSON array of last 5 video IDs
    last_video_published = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now)

# Dubbed News Tables
class DubbedNewsItem(Base):
    __tablename__ = "dubbed_news"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    link = Column(String, unique=True)
    summary = Column(String)
    published = Column(DateTime)
    source = Column(String)
    image_url = Column(String, nullable=True)
    video_id = Column(String, nullable=True)
    is_important = Column(Integer, default=0)
    importance_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class DubbedChannelLastVideo(Base):
    __tablename__ = "dubbed_channel_last_video"
    id = Column(Integer, primary_key=True, index=True)
    channel_name = Column(String, unique=True)
    last_video_ids = Column(String)  # JSON array of last 5 video IDs
    last_video_published = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now)

# Newspaper News Tables
class NewspaperNewsItem(Base):
    __tablename__ = "newspaper_news"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    link = Column(String, unique=True)
    summary = Column(String)
    published = Column(DateTime)
    source = Column(String)
    image_url = Column(String, nullable=True)
    article_id = Column(String, nullable=True)  # Unique article identifier
    is_important = Column(Integer, default=0)
    importance_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

class NewspaperLastArticle(Base):
    __tablename__ = "newspaper_last_article"
    id = Column(Integer, primary_key=True, index=True)
    source_name = Column(String, unique=True)
    last_article_ids = Column(String)  # JSON array of last 5 article IDs/URLs
    last_article_published = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now)

class SystemState(Base):
    __tablename__ = "system_state"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True)
    value = Column(String)

# Event Timeline - Related news threads
class EventThread(Base):
    __tablename__ = "event_threads"
    id = Column(Integer, primary_key=True, index=True)
    news_id = Column(Integer, index=True)  # The news item this thread belongs to
    related_news_id = Column(Integer, index=True)  # Related news item
    news_type = Column(String)  # 'world', 'yemen', 'newspaper' - type of the main news
    related_news_type = Column(String)  # 'world', 'yemen', 'newspaper' - type of the related news
    thread_title = Column(String)  # Arabic title for the event thread
    similarity_reason = Column(String)  # Why these are related
    created_at = Column(DateTime, default=datetime.now)

class NewsEmbeddingCache(Base):
    __tablename__ = "news_embedding_cache"
    id = Column(Integer, primary_key=True, index=True)
    news_id = Column(Integer, index=True)
    news_type = Column(String)
    title_hash = Column(String, unique=True, index=True)
    embedding = Column(String)
    created_at = Column(DateTime, default=datetime.now)

class NewsCluster(Base):
    __tablename__ = "news_clusters"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    intensity = Column(String, default="important")
    is_event = Column(Integer, default=1)
    representative_embedding = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)

class NewsClusterMember(Base):
    __tablename__ = "news_cluster_members"
    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, index=True)
    news_id = Column(Integer, index=True)
    news_type = Column(String)
    added_at = Column(DateTime, default=datetime.now)

Base.metadata.create_all(bind=engine)

# Migration: Add video_id column and channel_last_video table
def migrate_database():
    """Add missing columns and tables to existing database"""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Check if video_id column exists in news table
            result = conn.execute(text("PRAGMA table_info(news)"))
            columns = [row[1] for row in result]
            
            if 'video_id' not in columns:
                logger.info("Adding video_id column to news table...")
                conn.execute(text("ALTER TABLE news ADD COLUMN video_id VARCHAR"))
                try: conn.commit() 
                except: pass 
            
            if 'created_at' not in columns:
                logger.info("Adding created_at column to news table...")
                conn.execute(text("ALTER TABLE news ADD COLUMN created_at DATETIME"))
                try: conn.commit() 
                except: pass 

            if 'is_important' not in columns:
                logger.info("Adding is_important column to news table...")
                conn.execute(text("ALTER TABLE news ADD COLUMN is_important INTEGER DEFAULT 0"))
                try: conn.commit() 
                except: pass 
            
            if 'importance_reason' not in columns:
                logger.info("Adding importance_reason column to news table...")
                conn.execute(text("ALTER TABLE news ADD COLUMN importance_reason VARCHAR"))
                try: conn.commit() 
                except: pass 

            # Check for yemen_news columns
            result = conn.execute(text("PRAGMA table_info(yemen_news)"))
            yemen_columns = [row[1] for row in result]
            if 'created_at' not in yemen_columns:
                logger.info("Adding created_at column to yemen_news table...")
                conn.execute(text("ALTER TABLE yemen_news ADD COLUMN created_at DATETIME"))
                try: conn.commit() 
                except: pass 

            if 'is_important' not in yemen_columns:
                logger.info("Adding is_important column to yemen_news table...")
                conn.execute(text("ALTER TABLE yemen_news ADD COLUMN is_important INTEGER DEFAULT 0"))
                try: conn.commit() 
                except: pass 
            
            if 'importance_reason' not in yemen_columns:
                logger.info("Adding importance_reason column to yemen_news table...")
                conn.execute(text("ALTER TABLE yemen_news ADD COLUMN importance_reason VARCHAR"))
                try: conn.commit() 
                except: pass 
            
            # Check if channel_last_video table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='channel_last_video'"))
            if not result.fetchone():
                logger.info("Creating channel_last_video table...")
                ChannelLastVideo.__table__.create(engine)
                logger.info("Successfully created channel_last_video table")
            else:
                # Check if we need to migrate from last_video_id to last_video_ids
                result = conn.execute(text("PRAGMA table_info(channel_last_video)"))
                columns = [row[1] for row in result]
                
                if 'last_video_id' in columns and 'last_video_ids' not in columns:
                    logger.info("Migrating channel_last_video table to use last_video_ids...")
                    # Add new column
                    conn.execute(text("ALTER TABLE channel_last_video ADD COLUMN last_video_ids VARCHAR"))
                    try: conn.commit()
                    except: pass
                    
                    # Migrate existing data
                    result = conn.execute(text("SELECT id, last_video_id FROM channel_last_video WHERE last_video_id IS NOT NULL"))
                    for row in result:
                        record_id, old_video_id = row
                        # Convert single ID to JSON array
                        new_video_ids = json.dumps([old_video_id])
                        conn.execute(text(f"UPDATE channel_last_video SET last_video_ids = '{new_video_ids}' WHERE id = {record_id}"))
                    try: conn.commit()
                    except: pass
                    logger.info("Successfully migrated channel_last_video data")
            
            # Check if yemen_news table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='yemen_news'"))
            if not result.fetchone():
                logger.info("Creating yemen_news table...")
                YemenNewsItem.__table__.create(engine)
                logger.info("Successfully created yemen_news table")
            
            # Check if yemen_channel_last_video table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='yemen_channel_last_video'"))
            if not result.fetchone():
                logger.info("Creating yemen_channel_last_video table...")
                YemenChannelLastVideo.__table__.create(engine)
                logger.info("Successfully created yemen_channel_last_video table")
            
            # Check if system_state table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='system_state'"))
            if not result.fetchone():
                logger.info("Creating system_state table...")
                SystemState.__table__.create(engine)
                logger.info("Successfully created system_state table")
            
            # Check if newspaper_news table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='newspaper_news'"))
            if not result.fetchone():
                logger.info("Creating newspaper_news table...")
                NewspaperNewsItem.__table__.create(engine)
                logger.info("Successfully created newspaper_news table")
            else:
                result = conn.execute(text("PRAGMA table_info(newspaper_news)"))
                newspaper_columns = [row[1] for row in result]
                if 'is_important' not in newspaper_columns:
                    logger.info("Adding is_important column to newspaper_news table...")
                    conn.execute(text("ALTER TABLE newspaper_news ADD COLUMN is_important INTEGER DEFAULT 0"))
                    try: conn.commit()
                    except: pass
                if 'importance_reason' not in newspaper_columns:
                    logger.info("Adding importance_reason column to newspaper_news table...")
                    conn.execute(text("ALTER TABLE newspaper_news ADD COLUMN importance_reason VARCHAR"))
                    try: conn.commit()
                    except: pass
            
            # Check if dubbed_news table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='dubbed_news'"))
            if not result.fetchone():
                logger.info("Creating dubbed_news table...")
                DubbedNewsItem.__table__.create(engine)
                logger.info("Successfully created dubbed_news table")
            
            # Check if dubbed_channel_last_video table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='dubbed_channel_last_video'"))
            if not result.fetchone():
                logger.info("Creating dubbed_channel_last_video table...")
                DubbedChannelLastVideo.__table__.create(engine)
                logger.info("Successfully created dubbed_channel_last_video table")

            # Check if newspaper_last_article table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='newspaper_last_article'"))
            if not result.fetchone():
                logger.info("Creating newspaper_last_article table...")
                NewspaperLastArticle.__table__.create(engine)
                logger.info("Successfully created newspaper_last_article table")
            
            # Check if news_embedding_cache table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='news_embedding_cache'"))
            if not result.fetchone():
                logger.info("Creating news_embedding_cache table...")
                NewsEmbeddingCache.__table__.create(engine)
                logger.info("Successfully created news_embedding_cache table")

            # Check if news_clusters table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='news_clusters'"))
            if not result.fetchone():
                logger.info("Creating news_clusters table...")
                NewsCluster.__table__.create(engine)
                logger.info("Successfully created news_clusters table")

            # Check if news_cluster_members table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='news_cluster_members'"))
            if not result.fetchone():
                logger.info("Creating news_cluster_members table...")
                NewsClusterMember.__table__.create(engine)
                logger.info("Successfully created news_cluster_members table")

            # Check if event_threads table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='event_threads'"))
            if not result.fetchone():
                logger.info("Creating event_threads table...")
                EventThread.__table__.create(engine)
                logger.info("Successfully created event_threads table")
            else:
                # Check if related_news_type column exists
                result = conn.execute(text("PRAGMA table_info(event_threads)"))
                event_columns = [row[1] for row in result]
                if 'related_news_type' not in event_columns:
                    logger.info("Adding related_news_type column to event_threads table...")
                    conn.execute(text("ALTER TABLE event_threads ADD COLUMN related_news_type VARCHAR"))
                    # Set default value for existing rows
                    conn.execute(text("UPDATE event_threads SET related_news_type = news_type WHERE related_news_type IS NULL"))
                    try: conn.commit()
                    except: pass
                    logger.info("Successfully added related_news_type column")
    except Exception as e:
        logger.error(f"Migration error: {e}")

# Run migration on startup
migrate_database()

# OpenAI API for finding related news
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

async def process_event_timeline(db, news_id: int, news_title: str, news_summary: str, news_type: str):
    """Process and store event timeline for a new news item - searches across ALL news types"""
    try:
        # Get news from ALL types to find related ones
        world_news = db.query(NewsItem).order_by(desc(NewsItem.created_at)).limit(200).all()
        yemen_news = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.created_at)).limit(200).all()
        newspaper_news = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.created_at)).limit(200).all()
        
        # Prepare combined news list with type prefix to identify source
        # Format: "type:id" to track which table each news comes from
        all_news_combined = []
        
        for n in world_news:
            if not (news_type == 'world' and n.id == news_id):
                all_news_combined.append({"id": f"world:{n.id}", "title": n.title, "type": "world", "real_id": n.id})
        
        for n in yemen_news:
            if not (news_type == 'yemen' and n.id == news_id):
                all_news_combined.append({"id": f"yemen:{n.id}", "title": n.title, "type": "yemen", "real_id": n.id})
        
        for n in newspaper_news:
            if not (news_type == 'newspaper' and n.id == news_id):
                all_news_combined.append({"id": f"newspaper:{n.id}", "title": n.title, "type": "newspaper", "real_id": n.id})

        dubbed_news = db.query(DubbedNewsItem).order_by(desc(DubbedNewsItem.created_at)).limit(200).all()
        for n in dubbed_news:
            if not (news_type == 'dubbed' and n.id == news_id):
                all_news_combined.append({"id": f"dubbed:{n.id}", "title": n.title, "type": "dubbed", "real_id": n.id})
        
        if not all_news_combined:
            return
        
        # Find related news using AI (searches across all types)
        result = await find_related_news_with_ai(news_title, news_summary, all_news_combined, news_type)
        
        if result.get("thread_title") and result.get("related_ids"):
            # Store the event threads
            for related_id_str in result["related_ids"]:
                try:
                    # Parse the type:id format
                    if isinstance(related_id_str, str) and ':' in related_id_str:
                        related_type, related_id = related_id_str.split(':', 1)
                        related_id = int(related_id)
                    else:
                        # Fallback for old format (just ID) - assume same type
                        related_type = news_type
                        related_id = int(related_id_str)
                    
                    # Check if this relationship already exists
                    existing = db.query(EventThread).filter(
                        EventThread.news_id == news_id,
                        EventThread.related_news_id == related_id,
                        EventThread.news_type == news_type,
                        EventThread.related_news_type == related_type
                    ).first()
                    
                    if not existing:
                        thread = EventThread(
                            news_id=news_id,
                            related_news_id=related_id,
                            news_type=news_type,
                            related_news_type=related_type,
                            thread_title=result["thread_title"],
                            similarity_reason=result.get("reason", "")
                        )
                        db.add(thread)
                except Exception as e:
                    logger.error(f"Error adding event thread: {e}")
                    continue
            
            db.commit()
            logger.info(f"[Timeline] Added {len(result['related_ids'])} related news for {news_type} news ID {news_id}: {result['thread_title']}")
    except Exception as e:
        logger.error(f"Error in process_event_timeline: {e}")
        db.rollback()

async def find_related_news_with_ai(current_news_title: str, current_news_summary: str, all_news_titles: List[dict], news_type: str) -> dict:
    """Use GPT-4o-mini to find related news and generate Arabic thread title"""
    if not OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY not set, skipping AI-based related news")
        return {"thread_title": "", "related_ids": [], "reason": ""}
    
    try:
        # Prepare the news list for AI - include more items since we're combining all sources
        news_list_text = "\n".join([f"ID: {n['id']} - العنوان: {n['title']}" for n in all_news_titles[:300]])
        
        prompt = f"""أنت محلل أخبار خبير. مهمتك هي إيجاد الأخبار المرتبطة بموضوع معين.

الخبر الحالي:
العنوان: {current_news_title}
الملخص: {current_news_summary}

قائمة الأخبار المتاحة:
{news_list_text}

المطلوب:
1. أعطني عنوان عربي قصير وجذاب لـ"خيط الحدث" يصف الموضوع الرئيسي (مثال: "أزمة ميناء الحديدة" أو "التصعيد في البحر الأحمر")
2. أعطني قائمة بـ IDs الأخبار المرتبطة بنفس الموضوع (الحد الأقصى 10 أخبار)
3. اشرح باختصار لماذا هذه الأخبار مرتبطة

أجب بصيغة JSON فقط كالتالي:
{{
    "thread_title": "عنوان الخيط بالعربية",
    "related_ids": [1, 2, 3],
    "reason": "سبب الترابط باختصار"
}}

إذا لم تجد أخبار مرتبطة، أرجع:
{{
    "thread_title": "",
    "related_ids": [],
    "reason": ""
}}"""

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "أنت محلل أخبار خبير تجيب بصيغة JSON فقط."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        
        response = await asyncio.to_thread(
            lambda: requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            # Parse JSON from response
            import json
            # Clean the response if it has markdown code blocks
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()
            
            parsed = json.loads(content)
            return parsed
        else:
            logger.error(f"OpenAI API error: {response.status_code} - {response.text}")
            return {"thread_title": "", "related_ids": [], "reason": ""}
            
    except Exception as e:
        logger.error(f"Error in find_related_news_with_ai: {e}")
        return {"thread_title": "", "related_ids": [], "reason": ""}

# YouTube Channels List - includes channels and playlists
YOUTUBE_CHANNELS = [
    {"url": "https://www.youtube.com/@Reuters/videos", "name": "Reuters", "type": "channel"},
    {"url": "https://www.youtube.com/@aljazeeraenglish/videos", "name": "Al Jazeera English", "type": "channel"},
    {"url": "https://www.youtube.com/@AssociatedPress/videos", "name": "Associated Press", "type": "channel"},
    {"url": "https://www.youtube.com/@SkyNews/videos", "name": "Sky News", "type": "channel"},
    {"url": "https://www.youtube.com/@dwnews/videos", "name": "DW News", "type": "channel"},
    {"url": "https://www.youtube.com/@hossamnassar/videos", "name": "Hossam Nassar", "type": "channel"},
    {"url": "https://www.youtube.com/@ChrisHedgesChannel/videos", "name": "Chris Hedges", "type": "channel"},
    {"url": "https://www.youtube.com/@ABCNews/videos", "name": "ABC News", "type": "channel"},
    {"url": "https://www.youtube.com/facethenation/videos", "name": "Face The Nation", "type": "channel"},
    {"url": "https://www.youtube.com/@France24_en/videos", "name": "France 24 English", "type": "channel"},
    {"url": "https://www.youtube.com/@CBNnewsonline/videos", "name": "CBN News", "type": "channel"},
    {"url": "https://www.youtube.com/playlist?list=PLBPmhDfEfvB88vi4wFeqElRq_K-lxaBcV", "name": "Sky News Arabia Playlist", "type": "playlist"},
    {"url": "https://www.youtube.com/@BBCNews/videos", "name": "BBC News", "type": "channel"},
    {"url": "https://www.youtube.com/@ForbesBreakingNews/videos", "name": "Forbes Breaking News", "type": "channel"},
    {"url": "https://www.youtube.com/@FoxNews/videos", "name": "Fox News", "type": "channel"},
    {"url": "https://www.youtube.com/@NBCNews/videos", "name": "NBC News", "type": "channel"},
    {"url": "https://www.youtube.com/@markets/videos", "name": "Bloomberg Markets", "type": "channel"},
    {"url": "https://www.youtube.com/@euronews/videos", "name": "Euronews", "type": "channel"},
    {"url": "https://www.youtube.com/@trtworld/videos", "name": "TRT World", "type": "channel"},
    #{"url": "https://www.youtube.com/@WION/videos", "name": "WION", "type": "channel"},
    {"url": "https://www.youtube.com/@channelnewsasia/videos", "name": "Channel News Asia", "type": "channel"},
    {"url": "https://www.youtube.com/@globalnews/videos", "name": "Global News", "type": "channel"},
    {"url": "https://www.youtube.com/@TheAtlantic/videos", "name": "The Atlantic", "type": "channel"},
    {"url": "https://www.youtube.com/@breakingpoints/videos", "name": "Breaking Points", "type": "channel"},
    {"url": "https://www.youtube.com/@cfr/videos", "name": "CFR", "type": "channel"},
    {"url": "https://www.youtube.com/@MiddleEastEye/videos", "name": "Middle East Eye", "type": "channel"},
    {"url": "https://www.youtube.com/@AFP/videos", "name": "AFP", "type": "channel"},
    {"url": "https://www.youtube.com/@unitednations/videos", "name": "United Nations", "type": "channel"},
    {"url": "https://www.youtube.com/@PBSNewsHour/videos", "name": "PBS NewsHour", "type": "channel"},
    {"url": "https://www.youtube.com/@guardiannews/videos", "name": "Guardian News", "type": "channel"},
    {"url": "https://www.youtube.com/@axios/videos", "name": "Axios", "type": "channel"},
    {"url": "https://www.youtube.com/@talktv/videos", "name": "TalkTV", "type": "channel"},
    {"url": "https://www.youtube.com/@DemocracyNow/videos", "name": "Democracy Now", "type": "channel"},
    {"url": "https://www.youtube.com/@GBNewsOnline/videos", "name": "GB News", "type": "channel"},
    {"url": "https://www.youtube.com/@RedactedNews/videos", "name": "Redacted News", "type": "channel"},
]

# Yemen YouTube Channels List
YEMEN_YOUTUBE_CHANNELS = [
    {"url": "https://www.youtube.com/@Mohammed.Naser.Official/videos", "name": "محمد ناصر", "type": "channel"},
    {"url": "https://www.youtube.com/@aljazeera/videos", "name": "الجزيرة", "type": "channel"},
    {"url": "https://www.youtube.com/@raghebelsergany/videos", "name": "راغب السرجاني", "type": "channel"},
    {"url": "https://www.youtube.com/@AlarabyTv_News/videos", "name": "التلفزيون العربي", "type": "channel"},
    {"url": "https://www.youtube.com/@AlHadath/videos", "name": "الحدث", "type": "channel"},
    {"url": "https://www.youtube.com/@bbcnewsarabic/videos", "name": "بي بي سي عربي", "type": "channel"},
    {"url": "https://www.youtube.com/@AlArabiya/videos", "name": "العربية", "type": "channel"},
    {"url": "https://www.youtube.com/@ibrahiemmustafaelsharkawy/videos", "name": "إبراهيم مصطفى الشرقاوي", "type": "channel"},
    {"url": "https://www.youtube.com/@AlmahriahTV/videos", "name": "المهرية", "type": "channel"},
    {"url": "https://www.youtube.com/@Aimn_Al-Qasemi/videos", "name": "أيمن القاسمي", "type": "channel"},
    {"url": "https://www.youtube.com/@Ne3rafChannel/videos", "name": "نعرف", "type": "channel"},
    {"url": "https://www.youtube.com/@Sahmoo7/videos", "name": "سهمو", "type": "channel"},
    {"url": "https://www.youtube.com/@aljoumhouriyaTV/videos", "name": "الجمهورية", "type": "channel"},
    {"url": "https://www.youtube.com/@mns777/videos", "name": "MNS", "type": "channel"},
    {"url": "https://www.youtube.com/@yementvyem/videos", "name": "اليمن TV", "type": "channel"},
    {"url": "https://www.youtube.com/@TVyemenshabab/videos", "name": "قناة يمن شباب", "type": "channel"},
    {"url": "https://www.youtube.com/@AsharqNews/videos", "name": "الشرق للأخبار", "type": "channel"},
    {"url": "https://www.youtube.com/@Yementdy/videos", "name": "اليمن اليوم", "type": "channel"},
]

# Dubbed YouTube Channels List
DUBBED_YOUTUBE_CHANNELS = [
    {"url": "https://www.youtube.com/@TheEconomist/videos", "name": "The Economist", "type": "channel"},
    {"url": "https://www.youtube.com/@TheDuran/videos", "name": "The Duran", "type": "channel"},
    {"url": "https://www.youtube.com/@CBNnewsonline/videos", "name": "CBN News", "type": "channel"},
    {"url": "https://www.youtube.com/@Reuters/videos", "name": "Reuters", "type": "channel"},
    {"url": "https://www.youtube.com/@FoxNews/videos", "name": "Fox News", "type": "channel"},
    {"url": "https://www.youtube.com/@talktv/videos", "name": "TalkTV", "type": "channel"},
    {"url": "https://www.youtube.com/@GBNewsOnline/videos", "name": "GB News", "type": "channel"},
    {"url": "https://www.youtube.com/@PBSNewsHour/videos", "name": "PBS NewsHour", "type": "channel"},
    {"url": "https://www.youtube.com/@AlexChristoforou/videos", "name": "Alex Christoforou", "type": "channel"},
    {"url": "https://www.youtube.com/@ABCNews/videos", "name": "ABC News", "type": "channel"},
    {"url": "https://www.youtube.com/@BloombergPodcasts/videos", "name": "Bloomberg", "type": "channel"},
    {"url": "https://www.youtube.com/@SkyNews/videos", "name": "Sky News", "type": "channel"},
    {"url": "https://www.youtube.com/@judgingfreedom/videos", "name": "Judging Freedom", "type": "channel"},
    {"url": "https://www.youtube.com/@ForbesBreakingNews/videos", "name": "Forbes Breaking News", "type": "channel"},
]

# World Newspapers Sources List
NEWSPAPER_SOURCES = [
    {"url": "https://www.cbsnews.com/israel-gaza-conflict/", "name": "CBS News", "type": "newspaper"},
    {"url": "https://www.haaretz.com/", "name": "Haaretz", "type": "newspaper"},
    {"url": "https://www.nytimes.com/section/world/middleeast", "name": "NY Times", "type": "newspaper"},
    {"url": "https://www.ft.com/middle-east", "name": "Financial Times", "type": "newspaper"},
    {"url": "https://www.washingtonpost.com/world/middle-east/", "name": "Washington Post", "type": "newspaper"},
    {"url": "https://www.bbc.co.uk/news/world/middle_east", "name": "BBC News", "type": "newspaper"},
    {"url": "https://www.theguardian.com/world/middleeast", "name": "The Guardian", "type": "newspaper"},
    {"url": "https://foreignpolicy.com/tag/middle-east-and-north-africa/", "name": "Foreign Policy", "type": "newspaper"},
    {"url": "https://edition.cnn.com/world/middle-east", "name": "CNN", "type": "newspaper"},
    {"url": "https://apnews.com/hub/middle-east", "name": "AP News", "type": "newspaper"},
    {"url": "https://www.aljazeera.com/middle-east/", "name": "Al Jazeera", "type": "newspaper"},
    {"url": "https://www.axios.com/world", "name": "Axios", "type": "newspaper"},
    {"url": "https://www.seattletimes.com/nation-world/world/", "name": "Seattle Times", "type": "newspaper"},
    {"url": "https://www.reuters.com/world/middle-east/", "name": "Reuters", "type": "newspaper"},
    {"url": "https://news.un.org/en/focus-topic/middle-east", "name": "UN News", "type": "newspaper"},
    {"url": "https://www.ynetnews.com/category/3083", "name": "Ynet News", "type": "newspaper"},
    {"url": "https://www.bloomberg.com/middleeast", "name": "Bloomberg Middle East", "type": "newspaper"},
    {"url": "https://www.politico.com/news/middle-east", "name": "Politico", "type": "newspaper"},
    {"url": "https://www.independent.co.uk/news/world/middle-east", "name": "The Independent", "type": "newspaper"},
    {"url": "https://www.jpost.com/middle-east", "name": "Jerusalem Post", "type": "newspaper"},
    {"url": "https://www.middleeasteye.net/", "name": "Middle East Eye", "type": "newspaper"},
]

# Yemen news filter keywords
YEMEN_KEYWORDS = [
    "اليمن", "يمني", "يمنية", "اليمني", "اليمنية", "اليمنيين",
    "المجلس الانتقالي", "الانتقالي", "المجلس الرئاسي",
    "درع الوطن", "العمالقة", "الحزام الأمني",
    "عدن", "صنعاء", "تعز", "مأرب", "الحديدة", "شبوة", "حضرموت", "أبين", "لحج", "الضالع",
    "الحوثي", "الحوثيين", "أنصار الله",
    "التحالف العربي", "عاصفة الحزم",
    "الشرعية", "هادي", "العليمي"
]

def is_yemen_related(title: str) -> bool:
    """Check if the video title is related to Yemen news"""
    title_lower = title.lower()
    for keyword in YEMEN_KEYWORDS:
        if keyword in title or keyword.lower() in title_lower:
            return True
    return False

def generate_article_id(url: str) -> str:
    """Generate a unique ID for an article based on its URL"""
    return hashlib.md5(url.encode()).hexdigest()[:16]

# ============================================
# Geopolitical Heatmap - Country Location Data
# ============================================

COUNTRY_DATA = {}

def _add_country(key, lat, lng, ar, en, names):
    COUNTRY_DATA[key] = {"lat": lat, "lng": lng, "country": ar, "country_en": en, "names": names}

# Middle East & Gulf
_add_country("yemen", 15.55, 48.52, "اليمن", "Yemen", ["اليمن", "يمني", "يمنية", "اليمني", "اليمنية", "صنعاء", "عدن", "مأرب", "تعز", "الحديدة", "حضرموت", "شبوة", "أبين", "لحج", "الضالع", "الحوثي", "الحوثيين", "أنصار الله", "Yemen", "Sanaa", "Aden", "Houthi"])
_add_country("saudi", 24.71, 46.68, "السعودية", "Saudi Arabia", ["السعودية", "السعودي", "الرياض", "جدة", "مكة", "المدينة", "Saudi", "Riyadh", "Jeddah"])
_add_country("uae", 24.47, 54.37, "الإمارات", "UAE", ["الإمارات", "الإماراتي", "أبوظبي", "دبي", "UAE", "Emirates", "Abu Dhabi", "Dubai"])
_add_country("iran", 35.69, 51.39, "إيران", "Iran", ["إيران", "ايران", "الإيراني", "طهران", "خامنئي", "Iran", "Tehran", "Khamenei"])
_add_country("iraq", 33.31, 44.37, "العراق", "Iraq", ["العراق", "العراقي", "بغداد", "أربيل", "الموصل", "البصرة", "كردستان", "Iraq", "Baghdad", "Mosul", "Erbil"])
_add_country("syria", 33.51, 36.29, "سوريا", "Syria", ["سوريا", "السوري", "دمشق", "حلب", "إدلب", "الأسد", "Syria", "Damascus", "Aleppo", "Assad"])
_add_country("lebanon", 33.89, 35.50, "لبنان", "Lebanon", ["لبنان", "اللبناني", "بيروت", "حزب الله", "Lebanon", "Beirut", "Hezbollah"])
_add_country("jordan", 31.95, 35.93, "الأردن", "Jordan", ["الأردن", "الاردن", "الأردني", "Jordan", "Amman"])
_add_country("palestine", 31.50, 34.47, "فلسطين", "Palestine", ["فلسطين", "الفلسطيني", "غزة", "الضفة الغربية", "رام الله", "حماس", "الجهاد", "القدس", "Palestine", "Gaza", "Hamas", "West Bank", "Jerusalem"])
_add_country("israel", 31.77, 35.23, "إسرائيل", "Israel", ["إسرائيل", "اسرائيل", "الإسرائيلي", "تل أبيب", "نتنياهو", "الاحتلال", "Israel", "Tel Aviv", "Netanyahu", "IDF"])
_add_country("kuwait", 29.38, 47.99, "الكويت", "Kuwait", ["الكويت", "الكويتي", "Kuwait"])
_add_country("qatar", 25.29, 51.53, "قطر", "Qatar", ["قطر", "القطري", "الدوحة", "Qatar", "Doha"])
_add_country("bahrain", 26.07, 50.56, "البحرين", "Bahrain", ["البحرين", "البحريني", "المنامة", "Bahrain", "Manama"])
_add_country("oman", 23.59, 58.55, "عُمان", "Oman", ["سلطنة عمان", "عُمان", "مسقط", "Oman", "Muscat"])

# North Africa
_add_country("egypt", 30.04, 31.24, "مصر", "Egypt", ["مصر", "المصري", "القاهرة", "السيسي", "Egypt", "Cairo", "Sisi"])
_add_country("libya", 32.90, 13.18, "ليبيا", "Libya", ["ليبيا", "الليبي", "طرابلس", "بنغازي", "Libya", "Tripoli", "Benghazi"])
_add_country("tunisia", 36.81, 10.17, "تونس", "Tunisia", ["تونس", "التونسي", "Tunisia", "Tunis"])
_add_country("algeria", 36.75, 3.06, "الجزائر", "Algeria", ["الجزائر", "الجزائري", "Algeria", "Algiers"])
_add_country("morocco", 33.97, -6.85, "المغرب", "Morocco", ["المغرب", "المغربي", "الرباط", "Morocco", "Rabat"])
_add_country("sudan", 15.59, 32.53, "السودان", "Sudan", ["السودان", "السوداني", "الخرطوم", "Sudan", "Khartoum"])
_add_country("somalia", 2.05, 45.32, "الصومال", "Somalia", ["الصومال", "الصومالي", "مقديشو", "Somalia", "Mogadishu"])
_add_country("ethiopia", 9.02, 38.75, "إثيوبيا", "Ethiopia", ["إثيوبيا", "اثيوبيا", "أديس أبابا", "Ethiopia", "Addis Ababa"])

# Europe
_add_country("russia", 55.76, 37.62, "روسيا", "Russia", ["روسيا", "الروسي", "موسكو", "بوتين", "الكرملين", "Russia", "Moscow", "Putin", "Kremlin"])
_add_country("ukraine", 50.45, 30.52, "أوكرانيا", "Ukraine", ["أوكرانيا", "اوكرانيا", "الأوكراني", "كييف", "زيلينسكي", "Ukraine", "Kyiv", "Zelensky"])
_add_country("uk", 51.51, -0.13, "بريطانيا", "United Kingdom", ["بريطانيا", "البريطاني", "لندن", "Britain", "UK", "London", "England"])
_add_country("france", 48.86, 2.35, "فرنسا", "France", ["فرنسا", "الفرنسي", "باريس", "ماكرون", "France", "Paris", "Macron"])
_add_country("germany", 52.52, 13.41, "ألمانيا", "Germany", ["ألمانيا", "المانيا", "الألماني", "برلين", "Germany", "Berlin"])
_add_country("turkey", 39.93, 32.86, "تركيا", "Turkey", ["تركيا", "التركي", "أنقرة", "إسطنبول", "أردوغان", "Turkey", "Turkiye", "Ankara", "Istanbul", "Erdogan"])

# Asia
_add_country("china", 39.91, 116.40, "الصين", "China", ["الصين", "الصيني", "بكين", "شي جين بينغ", "China", "Beijing", "Xi Jinping"])
_add_country("japan", 35.68, 139.69, "اليابان", "Japan", ["اليابان", "الياباني", "طوكيو", "Japan", "Tokyo"])
_add_country("india", 28.61, 77.21, "الهند", "India", ["الهند", "الهندي", "نيودلهي", "مودي", "India", "New Delhi", "Modi"])
_add_country("north_korea", 39.02, 125.75, "كوريا الشمالية", "North Korea", ["كوريا الشمالية", "بيونغيانغ", "كيم جونغ", "North Korea", "Pyongyang", "Kim Jong"])
_add_country("south_korea", 37.57, 126.98, "كوريا الجنوبية", "South Korea", ["كوريا الجنوبية", "سيول", "South Korea", "Seoul"])
_add_country("afghanistan", 34.53, 69.17, "أفغانستان", "Afghanistan", ["أفغانستان", "افغانستان", "كابل", "طالبان", "Afghanistan", "Kabul", "Taliban"])
_add_country("pakistan", 33.69, 73.04, "باكستان", "Pakistan", ["باكستان", "إسلام آباد", "Pakistan", "Islamabad"])

# Americas
_add_country("usa", 38.91, -77.04, "أمريكا", "United States", ["أمريكا", "امريكا", "الأمريكي", "واشنطن", "البيت الأبيض", "البنتاغون", "الكونغرس", "ترامب", "بايدن", "USA", "United States", "Washington", "Pentagon", "White House", "Trump", "Biden", "Congress"])
_add_country("canada", 45.42, -75.70, "كندا", "Canada", ["كندا", "الكندي", "أوتاوا", "Canada", "Ottawa"])

# Other
_add_country("south_africa", -25.75, 28.19, "جنوب أفريقيا", "South Africa", ["جنوب أفريقيا", "South Africa", "Johannesburg"])
_add_country("red_sea", 20.00, 38.50, "البحر الأحمر", "Red Sea", ["البحر الأحمر", "باب المندب", "Red Sea", "Bab el-Mandeb"])
_add_country("un_hq", 46.23, 6.14, "الأمم المتحدة", "United Nations", ["الأمم المتحدة", "مجلس الأمن", "United Nations", "Security Council"])

# Build fast name → country_key lookup
NAME_TO_COUNTRY = {}
for _key, _data in COUNTRY_DATA.items():
    for _name in _data["names"]:
        NAME_TO_COUNTRY[_name] = _key

# Intensity classification keywords
CONFLICT_KEYWORDS_GEO = [
    "حرب", "هجوم", "قصف", "غارة", "غارات", "صاروخ", "صواريخ", "قتل", "مقتل", "قتلى",
    "ضحايا", "شهداء", "شهيد", "اشتباك", "اشتباكات", "معارك", "معركة", "تفجير", "انفجار",
    "اغتيال", "عدوان", "قنبلة", "طائرة مسيرة", "دمار", "إبادة", "مجزرة",
    "war", "attack", "strike", "bomb", "kill", "killed", "missile", "combat",
    "explosion", "drone", "airstrike", "casualties", "dead", "destroyed"
]
CRISIS_KEYWORDS_GEO = [
    "أزمة", "توتر", "تصعيد", "عقوبات", "احتجاج", "احتجاجات", "انقلاب",
    "تهديد", "إنذار", "انتهاك", "خلاف", "نزاع", "حصار",
    "crisis", "tension", "sanctions", "protest", "escalation", "threat", "coup", "conflict"
]
POSITIVE_KEYWORDS_GEO = [
    "سلام", "اتفاقية", "اتفاق", "تعاون", "وقف إطلاق النار", "هدنة", "مفاوضات",
    "إغاثة", "مساعدات", "إنسانية", "دبلوماسية", "تطبيع", "مصالحة",
    "peace", "agreement", "cooperation", "ceasefire", "truce", "humanitarian",
    "aid", "diplomacy", "negotiation", "reconciliation"
]
INTENSITY_RANK = {"positive": 1, "important": 2, "crisis": 3, "conflict": 4}

# Broad Topics for News Categorization
NEWS_TOPICS = {
    "أخبار اليمن": ["اليمن", "صنعاء", "عدن", "تعز", "مأرب", "الحوثي", "الحديدة", "المجلس الرئاسي"],
    "قضية فلسطين": ["غزة", "فلسطين", "القدس", "رام الله", "الاحتلال", "حماس", "الجهاد", "الرفح"],
    "البحر الأحمر والملاحة": ["البحر الأحمر", "باب المندب", "السفن", "الملاحة", "سنتكوم", "كيربي"],
    "أخبار إقليمية": ["السعودية", "الإمارات", "إيران", "مصر", "الأردن", "لبنان", "سوريا", "بيروت"],
    "أخبار دولية": ["أمريكا", "واشنطن", "بايدن", "ترامب", "روسيا", "أوكرانيا", "الصين", "بريطانيا", "فرنسا", "ألمانيا"],
    "اقتصاد وأعمال": ["اقتصاد", "الذهب", "النفط", "الدولار", "العملات", "أسواق", "شركات", "تداول", "استثمار"],
    "تكنولوجيا وعلوم": ["تكنولوجيا", "ذكاء اصطناعي", "آيفون", "سامسونج", "اكتشاف", "فضاء", "علمي"],
    "رياضة": ["كأس", "مباراة", "ريال مدريد", "برشلونة", "دوري", "هدف", "كرة القدم"],
    "منوعات وصحة": ["صحة", "طب", "فن", "فنان", "دراسة", "نصائح", "عالم", "غريب"]
}

def identify_topic(title: str, summary: str = "") -> str:
    """Identify the broad topic of a news item based on keywords"""
    text = (title + " " + (summary or "")).lower()
    
    # Track matches for each topic
    matches = {topic: 0 for topic in NEWS_TOPICS}
    
    for topic, keywords in NEWS_TOPICS.items():
        for kw in keywords:
            if kw in text:
                matches[topic] += 1
                
    # Get topic with most matches
    best_topic = max(matches.items(), key=lambda x: x[1])
    if best_topic[1] > 0:
        return best_topic[0]
    
    return "أخبار عامة"

def extract_locations_from_title(title):
    """Extract country locations mentioned in a news title"""
    found = set()
    if not title:
        return found
    
    # First check for multi-word names or priority names
    # Sort names by length descending to match longer names first (e.g., "الولايات المتحدة" before "عمان")
    sorted_names = sorted(NAME_TO_COUNTRY.items(), key=lambda x: len(x[0]), reverse=True)
    
    for name, country_key in sorted_names:
        if name in title:
            found.add(country_key)
            
    return found

def classify_news_intensity(title):
    """Classify news intensity based on keywords in title"""
    if not title:
        return "important"
    title_lower = title.lower()
    for kw in CONFLICT_KEYWORDS_GEO:
        if kw in title or kw in title_lower:
            return "conflict"
    for kw in CRISIS_KEYWORDS_GEO:
        if kw in title or kw in title_lower:
            return "crisis"
    for kw in POSITIVE_KEYWORDS_GEO:
        if kw in title or kw in title_lower:
            return "positive"
    return "important"

def translate_to_arabic(text: str) -> str:
    """Translate English text to Arabic using Google Translate free API"""
    if not text or any(char in text for char in 'أبتثجحخدذرزسشصضطظعغفقكلمنهوي'): # Skip if already has Arabic chars
        return text
    
    try:
        # Using the unofficial but widely used Google Translate API endpoint
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ar&dt=t&q={quote(text)}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            translated_text = "".join([segment[0] for segment in result[0] if segment[0]])
            return translated_text
        return text
    except Exception as e:
        logger.warning(f"Translation skipped (timeout/error): {e}")
        return text

# ============================================
# World News Video Processing (Manual AI)
# ============================================

# Telegram Settings (from telegram_to_facebook.py)
API_ID = int(os.environ.get("API_ID", "39973736"))
API_HASH = os.environ.get("API_HASH", "85c0ad15e89597740a41ecf4d4b21100")
MY_CHANNEL_URL = "https://t.me/osamaalshahape"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8652668769:AAGUMELS4sWpcKZ5WSTxqFW8BUhiz-VwrgE")

# Initialize Telegram Client
bot_client = TelegramClient(StringSession(), API_ID, API_HASH)

# التحكم في أولوية النشر
pause_background_tasks = asyncio.Event()
pause_background_tasks.set()  # مسموح بالعمل في الحالة العادية

async def post_to_telegram_channel(message_text):
    """نشر الرسالة إلى قناة تيليجرام المحددة."""
    try:
        if not bot_client.is_connected():
            await bot_client.start(bot_token=BOT_TOKEN)
        
        entity = await bot_client.get_entity(MY_CHANNEL_URL)
        await bot_client.send_message(entity, message_text)
        logger.info("✅ تم النشر في قناة تيليجرام بنجاح!")
        return True
    except Exception as e:
        logger.error(f"❌ فشل النشر في تيليجرام: {e}")
        return False

def fetch_youtube_transcript_downsub(video_url):
    """جلب نص الفيديو من DownSub مع مهل أطول وإعادة محاولة عند المهلات وأخطاء الشبكة."""
    api_url = 'https://api.downsub.com/download'
    headers = {
        'Authorization': 'Bearer AIzalTjrrsT1cKdr4HSWUryzgFRiqNYc8XBzztm',
        'Content-Type': 'application/json'
    }
    payload = {'url': video_url}
    max_retries = max(1, int(os.environ.get('DOWNSUB_RETRIES', '3')))
    post_timeout = int(os.environ.get('DOWNSUB_POST_TIMEOUT', '55'))
    get_timeout = int(os.environ.get('DOWNSUB_GET_TIMEOUT', '90'))

    last_err: Optional[str] = None
    for attempt in range(1, max_retries + 1):
        data = None
        try:
            logger.info(f"📡 [DownSub] محاولة {attempt}/{max_retries} — طلب المعالجة (مهلة {post_timeout}s)...")
            resp = requests.post(api_url, headers=headers, json=payload, timeout=post_timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = str(e)
            logger.warning(f"⚠️ [DownSub] مهلة أو فشل اتصال: {e}")
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 12))
            continue
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else 0
            last_err = str(e)
            if code >= 500 and attempt < max_retries:
                logger.warning(f"⚠️ [DownSub] HTTP {code} — إعادة المحاولة")
                time.sleep(min(2 ** (attempt - 1), 12))
                continue
            logger.error(f"🚨 [DownSub] خطأ HTTP: {e}")
            return None, None, str(e)
        except ValueError as e:
            last_err = str(e)
            logger.warning(f"⚠️ [DownSub] رد JSON غير صالح: {e}")
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 12))
            continue
        except Exception as e:
            logger.error(f"🚨 [DownSub] خطأ غير متوقع: {e}")
            return None, None, str(e)

        if data.get('status') != 'success':
            logger.error(f"❌ [DownSub] رد غير ناجح من الخادم: {data.get('message')}")
            return None, None, "فشل في جلب بيانات الفيديو من المصدر"

        original_subs = data.get('data', {}).get('subtitles', [])
        if not original_subs:
            logger.warning(f"⚠️ [DownSub] لم يتم العثور على أي ترجمات لهذا الفيديو.")
            return None, None, "لم يتم العثور على ترجمة أصلية"

        selected_sub = original_subs[0]
        for sub in original_subs:
            if "auto-generated" not in sub.get('language', '').lower():
                selected_sub = sub
                break

        txt_url = None
        for fmt in selected_sub.get('formats', []):
            if fmt.get('format') == 'txt':
                txt_url = fmt.get('url')
                break

        if not txt_url:
            logger.error(f"❌ [DownSub] لم يتم العثور على رابط لملف TXT.")
            return None, None, "لم يتم العثور على صيغة نصية (TXT)"

        page_title = data.get('data', {}).get('title')
        try:
            logger.info(f"📡 [DownSub] تحميل ملف TXT (مهلة {get_timeout}s)...")
            txt_resp = requests.get(txt_url, timeout=get_timeout)
            txt_resp.raise_for_status()
            logger.info(f"✅ [DownSub] اكتمل تحميل النص بنجاح.")
            return txt_resp.text, page_title, None
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_err = str(e)
            logger.warning(f"⚠️ [DownSub] فشل تحميل TXT: {e}")
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 12))
            continue
        except requests.exceptions.HTTPError as e:
            last_err = str(e)
            if e.response is not None and e.response.status_code >= 500 and attempt < max_retries:
                logger.warning(f"⚠️ [DownSub] فشل تحميل TXT HTTP — إعادة المحاولة")
                time.sleep(min(2 ** (attempt - 1), 12))
                continue
            logger.error(f"🚨 [DownSub] خطأ تحميل TXT: {e}")
            return None, None, str(e)

    return None, None, last_err or "فشل الاتصال بـ DownSub بعد عدة محاولات"

async def translate_title_ai(english_title: str) -> str:
    """ترجمة عنوان الفيديو إلى العربية بأسلوب إخباري باستخدام AI."""
    if not english_title or not OPENAI_API_KEY:
        return english_title
        
    prompt = f"قم بترجمة هذا العنوان الإخباري إلى لغة عربية سليمة وجذابة (عنوان إخباري فقط): {english_title}"
    try:
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3
        }
        response = await asyncio.to_thread(
            lambda: requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content'].strip().strip('"')
        return english_title
    except:
        return english_title

async def summarize_world_video_ai(transcript, original_url):
    """تلخيص النص باستخدام OpenAI (منطق telegram_to_facebook.py)."""
    if not OPENAI_API_KEY:
        return None, "OpenAI API Key is missing"
    
    system_prompt = (
        "اريد ان تدخل في الموضوع مباشرة ولا تضيف اي شي اخر. "
        "أنت كاتب عربي يصوغ ملخصات تبدو بشرية وطبيعية.\n"
        "اكتب فقرة واحدة أو اثنتين مترابطتين تشرح الفكرة الأساسية وأهم الرسائل أو النتائج "
        "الواردة في المقالة، بصياغة مباشرة وواضحة.\n"
        "تجنّب تمامًا العبارات التي تكشف أن النص ملخص أو أنه مأخوذ من مقالة، "
        'مثل: «تتحدث المقالة عن»، «في هذه المقالة»، «في هذا النص»، «هذا الملخص»، أو ما يشبهها.\n'
        "اكتب المحتوى مباشرة بصيغة تقريرية إخبارية، كما لو كنت تكتب خبراً صحفياً."
    )
    user_prompt = (
        "استخرج أهم ما يفيد القارئ من النص التالي، واكتبه في فقرة أو فقرتين عربيتين متصلتين، "
        "بدون تعداد نقاط وبدون الإشارة إلى كلمة مقالة أو نص أو ملخص:\n\n"
        f"{transcript}"
    )

    try:
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.5
        }
        
        response = await asyncio.to_thread(
            lambda: requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=40)
        )
        
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content'].strip()
            # استخراج العنوان للترجمة (أول جملة أو عنوان افتراضي)
            return content, None
        return None, f"AI Error: {response.status_code}"
    except Exception as e:
        return None, str(e)

async def analyze_geopolitical_ai(text):
    """تحليل جيوسياسي استراتيجي للنص بناءً على برومبت المستخدم."""
    if not OPENAI_API_KEY:
        return None, "OpenAI API Key is missing"
        
    system_prompt = """
الدور:
أنت محلل جيوسياسي استراتيجي مخضرم، وصائغ بيانات سياسية بلسان عربي رصين، مكثّف، عالي السياق. لا تتبنى الروايات الرسمية، بل تفككها وتكشف ما وراءها من مصالح وصراعات خفية.

المهمة:
سيتم تزويدك بمجموعة أخبار أو تقارير. مهمتك ليست تلخيصها، بل إعادة تركيبها في "سرد تحليلي واحد" يكشف الترابط العميق بين الأحداث ويعرّي البنية الحقيقية للمشهد الدولي.

قواعد التحليل:
ركّز على جوهر الصراع: تضارب المصالح، النفاق السياسي، هيمنة القوى الكبرى، الحروب بالوكالة، واستغلال الشعوب. تجاهل التفاصيل الصحفية غير المؤثرة مثل الأسماء الثانوية والتواريخ الدقيقة.

افترض دائماً سوء النية. ما يبدو "خطأ" هو في الغالب سياسة، وما يُعرض كـ"مبادرة إنسانية" قد يكون أداة نفوذ.

قواعد الأسلوب:
استخدم لغة نارية، مكثفة، وحاسمة. فضّل مفردات مثل: وصاية، ابتزاز، هندسة المجتمعات، مقايضة الدم، استنزاف، نفاق دولي، تدوير الأزمات، استعمار مقنّع.

ابنِ التحليل على المفارقات: سلام يُسوّق بالسلاح، مساعدات تُدار كأدوات سيطرة، قوانين تُفصّل لحماية الجناة.

اربط بين الأحداث المختلفة لصناعة صورة بانورامية واحدة تُظهر أن ما يحدث ليس معزولاً بل جزء من منظومة متكاملة.

قواعد التنسيق:
ممنوع استخدام التعداد أو النقاط.
النص يجب أن يكون فقرة واحدة أو فقرتين مترابطتين فقط.
ابدأ مباشرة دون مقدمات أو تمهيد.

النبرة:
واقعية سوداوية حادة. لا حياد، لا توازن، لا تلطيف. الهدف إدانة البنية لا وصفها.

طريقة الإخراج:
نص تحليلي متماسك، كثيف، يجرّد الخطاب الدولي من شرعيته الأخلاقية ويكشفه كأداة إدارة للصراع لا حله.
"""
        
    user_prompt = f"""
حلّل النص التالي وفق القواعد المحددة، واصنع منه سرداً سياسياً واحداً مكثفاً:

ادخل في صلب الموضوع مباشرة دون أي مقدمات.

ارفع مستوى الاتهام: لا تكتفِ بوصف التناقضات، بل أصدر أحكاماً واضحة وصريحة. سمِّ الأشياء بأسمائها: احتلال، إبادة بطيئة، ابتزاز، استعمار.

تعامل مع المشهد كمنظومة جريمة:
ضحايا يتم طمسهم، فاعلون يكتبون القواعد، وخطاب دولي يبرر.

اريد ان يكون الكلام حاد 
التزم بالتالي:
- كل جملة يجب أن تضيف فكرة جديدة (ممنوع التكرار)
- لا تعيد نفس المعنى بصيغ مختلفة
- استخدم منطق (سبب → نتيجة → تأثير)
- اجعل النقد واضح لكن بدون مبالغة لغوية

ممنوع أي خاتمة متفائلة. يجب أن تنتهي بخلاصة قاتمة تؤكد أن ما يحدث ممنهج ومستمر.

النص:
{text}
"""

    try:
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-5.4",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.5
        }
        
        response = await asyncio.to_thread(
            lambda: requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
        )
        
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content'].strip(), None
        return None, f"Geopolitical AI Error: {response.status_code}"
    except Exception as e:
        return None, str(e)

async def run_video_processing_flow(
    video_url: str,
    *,
    fallback_title: Optional[str] = None,
    fallback_summary: Optional[str] = None,
    skip_transcript: bool = False,
):
    """جلب النص (أو تخطيه) → تلخيص/ملخص احتياطي → ترجمة عنوان → نشر. عند الإلغاء (reload) يُسجَّل تحذير ويُعاد رفع التجميد."""
    pause_background_tasks.clear()
    logger.info("--- 🚀 [أولوية قصوى] بدء عملية النشر، تم تجميد مهام الخلفية مؤقتاً ---")

    def _fallback_ok() -> bool:
        return bool(fallback_summary and len(fallback_summary.strip()) >= 25)

    async def _publish_db_fallback(reason: str) -> tuple:
        if not _fallback_ok():
            return None, reason
        logger.warning(f"📎 نشر احتياطي من ملخص التطبيق ({reason})")
        translated_title = await translate_title_ai((fallback_title or "").strip() or "خبر")
        body = (fallback_summary or "").strip()
        final_message = f"📌 **{translated_title}**\n\n{body}\n\n🔗 {video_url}"
        ok = await post_to_telegram_channel(final_message)
        if ok:
            logger.info("🎉 تم النشر (من الملخص المخزن).")
            return body, "نُشر باستخدام الملخص المخزن (تعذّر الاعتماد على نص الفيديو)."
        return None, "فشل النشر في تيليجرام"

    try:
        if skip_transcript and _fallback_ok():
            logger.info("⏩ وضع سريع: تخطي DownSub والنشر من عنوان/ملخص البطاقة.")
            translated_title = await translate_title_ai((fallback_title or "").strip() or "خبر")
            body = (fallback_summary or "").strip()
            
            # المنشور الأول (التلخيص)
            final_message_1 = f"📌 **{translated_title}**\n\n{body}\n\n🔗 {video_url}"
            if await post_to_telegram_channel(final_message_1):
                logger.info("🎉 تم نشر المنشور الأول (التلخيص) بنجاح.")
                
                # المنشور الثاني (التحليل الجيوسياسي)
                geo_analysis, geo_error = await analyze_geopolitical_ai(body)
                if geo_analysis:
                    final_message_2 = f"\n\n{geo_analysis}\n\n🔗 {video_url}"
                    await post_to_telegram_channel(final_message_2)
                    logger.info("🎉 تم نشر المنشور الثاني (التحليل الجيوسياسي) بنجاح.")
                
                return body, None
            return None, "فشل النشر في تيليجرام"

        transcript = None
        original_title = None
        error = None

        if not skip_transcript:
            logger.info("⏳ [1/4] جاري استخلاص النصوص من يوتيوب (قد يستغرق وقتاً مع الفيديوهات الطويلة)...")
            transcript, original_title, error = await asyncio.to_thread(fetch_youtube_transcript_downsub, video_url)

        if skip_transcript or error or not transcript or len(transcript) < 10:
            if skip_transcript:
                return None, "تخطي النص مفعّل لكن لا يوجد ملخص كافٍ في البطاقة"
            if error:
                logger.error(f"❌ فشل جلب النص من DownSub: {error}")
            else:
                logger.warning("⚠️ النص المستخرج فارغ أو غير كافٍ.")
            fb_summary, fb_err = await _publish_db_fallback(error or "نص غير كافٍ")
            if fb_summary is not None:
                return fb_summary, fb_err
            base = error or "النص المستخرج غير كافٍ للتلخيص"
            return None, f"{base} — ولا يوجد ملخص احتياطي في البطاقة"

        logger.info(f"✅ تم استخلاص النص بنجاح! الطول: {len(transcript)} حرف.")

        logger.info("⏳ [2/4] جاري التلخيص والتحليل بالذكاء الاصطناعي...")
        # تنفيذ الطلبين بالتوازي لتوفير الوقت
        summary_task = summarize_world_video_ai(transcript, video_url)
        geo_task = analyze_geopolitical_ai(transcript)
        
        summary, ai_error = await summary_task
        geo_analysis, geo_error = await geo_task
        
        if ai_error:
            logger.error(f"❌ فشل التلخيص بالذكاء الاصطناعي: {ai_error}")
            fb_summary, fb_err = await _publish_db_fallback(f"فشل التلخيص: {ai_error}")
            if fb_summary is not None:
                return fb_summary, fb_err
            return None, f"فشل التلخيص: {ai_error}"

        logger.info("📝 اكتمل التلخيص والتحليل بنجاح.")

        logger.info("⏳ [3/4] جاري ترجمة العنوان بالـ AI...")
        translated_title = await translate_title_ai(original_title)

        logger.info("⏳ [4/4] جاري النشر النهائي للمنشورين...")
        # المنشور الأول (التلخيص)
        final_message_1 = f"📌 **{translated_title}**\n\n{summary}\n\n🔗 {video_url}"
        success_1 = await post_to_telegram_channel(final_message_1)

        if success_1:
            logger.info("🎉 تم نشر المنشور الأول (التلخيص) بنجاح!")
            
            # المنشور الثاني (التحليل الجيوسياسي)
            if geo_analysis:
                final_message_2 = f"\n\n{geo_analysis}\n\n🔗 {video_url}"
                await post_to_telegram_channel(final_message_2)
                logger.info("🎉 تم نشر المنشور الثاني (التحليل الجيوسياسي) بنجاح!")
            else:
                logger.warning(f"⚠️ تخطي المنشور الثاني بسبب خطأ في التحليل: {geo_error}")
                
            return summary, None
            
        fb_summary, fb_err = await _publish_db_fallback("فشل إرسال تيليجرام للرسالة الملخّصة")
        if fb_summary is not None:
            return fb_summary, fb_err
        return None, "فشل النشر في تيليجرام"

    except asyncio.CancelledError:
        logger.warning(
            "أُلغيت عملية النشر (غالباً بسبب إعادة تحميل Uvicorn عند حفظ الملفات مع --reload، أو إيقاف الخادم). "
            "لتفادي ذلك: لا تحفظ main.py أثناء النشر، أو شغّل الإنتاج بدون --reload."
        )
        raise
    finally:
        pause_background_tasks.set()

# Endpoint للمعالجة عبر رابط يدوي
@app.post("/api/process-world-video")
async def process_world_video_endpoint(payload: dict):
    video_url = payload.get("url")
    if not video_url:
        return {"error": "رابط الفيديو مطلوب"}, 400
    
    logger.info(f"🚀 بدء معالجة فيديو يدوي: {video_url}")
    summary, error = await run_video_processing_flow(video_url)
    
    if error and not summary:
        return {"error": error}, 500
    return {"status": "success" if not error else "partial_success", "message": error or "تمت المعالجة والنشر بنجاح!", "summary": summary}

# Endpoint للنشر المباشر من بطاقة الخبر
@app.post("/api/telegram-publish/{news_type}/{news_id}")
async def telegram_publish_by_id_endpoint(
    news_type: str,
    news_id: int,
    use_db_only: bool = Query(False, description="نشر سريع من عنوان/ملخص البطاقة دون جلب نص الفيديو من DownSub"),
):
    db = SessionLocal()
    try:
        # البحث عن الخبر للحصول على الرابط
        news_item = None
        if news_type == 'world':
            news_item = db.query(NewsItem).filter(NewsItem.id == news_id).first()
        elif news_type == 'yemen':
            news_item = db.query(YemenNewsItem).filter(YemenNewsItem.id == news_id).first()
        elif news_type == 'newspaper':
            news_item = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id == news_id).first()
            
        if not news_item or not news_item.link:
            return {"error": "الخبر غير موجود أو لا يحتوي على رابط"}, 404
        
        video_url = news_item.link
        logger.info(f"🚀 بدء نشر خبر من البطاقة ({news_type}:{news_id}): {video_url}")
        
        summary, error = await run_video_processing_flow(
            video_url,
            fallback_title=news_item.title,
            fallback_summary=news_item.summary,
            skip_transcript=use_db_only,
        )
        
        if error and not summary:
            return {"error": error}, 500
        return {"status": "success" if not error else "partial_success", "message": error or "تمت العملية بنجاح!", "summary": summary}
    finally:
        db.close()

# ============================================
# News Clustering - Embedding & Clustering Logic
# ============================================
_cluster_cache = {"data": None, "timestamp": None, "ttl": 600}
_search_rank_cache = {
    "google": {},
    "youtube": {},
    "ttl": 7200  # 2 hours
}
_google_rate_lock = threading.Lock()
_google_rate_state = {
    "next_allowed_at": 0.0,
    "blocked_until": 0.0,
    "consecutive_429": 0,
    "min_interval_sec": 2.0
}

def _get_cached_rank_result(provider: str, query: str):
    bucket = _search_rank_cache.get(provider, {})
    cached = bucket.get(query)
    if not cached:
        return None
    if (datetime.now() - cached["timestamp"]).total_seconds() > _search_rank_cache["ttl"]:
        bucket.pop(query, None)
        return None
    return cached["video_ids"]

def _set_cached_rank_result(provider: str, query: str, video_ids: List[str]):
    if provider not in _search_rank_cache:
        return
    _search_rank_cache[provider][query] = {
        "video_ids": video_ids,
        "timestamp": datetime.now()
    }

def _acquire_google_request_slot() -> bool:
    """Global throttle/cooldown gate for Google scraping requests."""
    with _google_rate_lock:
        now = time.time()
        blocked_until = _google_rate_state["blocked_until"]
        if blocked_until > now:
            return False

        scheduled_at = max(now, _google_rate_state["next_allowed_at"])
        _google_rate_state["next_allowed_at"] = scheduled_at + _google_rate_state["min_interval_sec"]

    wait = scheduled_at - time.time()
    if wait > 0:
        time.sleep(wait)
    return True

def _register_google_response(status_code: int):
    with _google_rate_lock:
        now = time.time()
        if status_code == 429:
            _google_rate_state["consecutive_429"] += 1
            strike = _google_rate_state["consecutive_429"]
            cooldown = min(900, 60 * (2 ** min(strike - 1, 4)))  # 60s,120s,240s,480s,900s max
            _google_rate_state["blocked_until"] = now + cooldown
            _google_rate_state["next_allowed_at"] = _google_rate_state["blocked_until"]
        elif 200 <= status_code < 300:
            _google_rate_state["consecutive_429"] = 0
            _google_rate_state["blocked_until"] = 0.0

def _should_skip_google_for_title(title: str) -> bool:
    """Skip noisy generic cluster titles to reduce unnecessary Google hits."""
    t = clean_news_text(title or "")
    return t.startswith("ملخص:")

async def call_openai_embeddings(titles: List[str]) -> Optional[List[List[float]]]:
    """Call OpenAI embeddings API for a batch of titles"""
    if not OPENAI_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "text-embedding-3-small",
            "input": titles
        }
        response = await asyncio.to_thread(
            lambda: requests.post(
                "https://api.openai.com/v1/embeddings",
                headers=headers,
                json=payload,
                timeout=60
            )
        )
        if response.status_code == 200:
            result = response.json()
            sorted_data = sorted(result["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]
        else:
            logger.error(f"OpenAI embeddings error: {response.status_code} - {response.text[:200]}")
            return None
    except Exception as e:
        logger.error(f"Error calling OpenAI embeddings: {e}")
        return None

def clean_news_text(text: str) -> str:
    """Clean news text by removing common prefixes and noise"""
    if not text:
        return ""
    # Remove common prefixes
    prefixes = ["عاجل..", "عاجل:", "عاجل", "شاهد..", "شاهد:", "شاهد", "فيديو..", "بالفيديو..", "بالفيديو:", "حصري..", "خاص.."]
    cleaned = text
    for p in prefixes:
        if cleaned.startswith(p):
            cleaned = cleaned[len(p):].strip()
    
    # Remove source names in brackets or before |
    import re
    cleaned = re.sub(r'\[.*?\]', '', cleaned)
    cleaned = re.sub(r'\(.*?\)', '', cleaned)
    if ' | ' in cleaned:
        cleaned = cleaned.split(' | ')[0]
    if ' - ' in cleaned:
        # Only take the first part if it's a short source name at the end
        parts = cleaned.split(' - ')
        if len(parts[-1]) < 20: # Likely a source name
            cleaned = ' - '.join(parts[:-1])
            
    return cleaned.strip()

async def get_embeddings_batch(db, news_items: List[dict]) -> List[List[float]]:
    """Get embeddings for news items, using DB cache when available"""
    embeddings = [None] * len(news_items)
    items_needing_embedding = []

    for i, item in enumerate(news_items):
        # Use both title and summary for better topic representation
        clean_title = clean_news_text(item.get("title", ""))
        clean_summary = clean_news_text(item.get("summary", ""))
        
        # Combine title and summary for embedding, but prioritize title
        text_for_embedding = f"{clean_title}\n{clean_summary}".strip()
        
        # We use a hash of the combined text to check cache
        title_hash = hashlib.md5(text_for_embedding.encode()).hexdigest()
        
        cached = db.query(NewsEmbeddingCache).filter(
            NewsEmbeddingCache.title_hash == title_hash
        ).first()
        
        if cached:
            try:
                embeddings[i] = json.loads(cached.embedding)
            except:
                items_needing_embedding.append((i, text_for_embedding, title_hash, item))
        else:
            items_needing_embedding.append((i, text_for_embedding, title_hash, item))

    if items_needing_embedding and OPENAI_API_KEY:
        batch_size = 100
        for batch_start in range(0, len(items_needing_embedding), batch_size):
            batch = items_needing_embedding[batch_start:batch_start + batch_size]
            texts = [text for _, text, _, _ in batch]
            new_embeddings = await call_openai_embeddings(texts)

            if new_embeddings:
                for j, (i, text_for_embedding, title_hash, item) in enumerate(batch):
                    if j < len(new_embeddings):
                        embeddings[i] = new_embeddings[j]
                        try:
                            # Avoid duplicate hash error if multiple threads/processes run
                            exists = db.query(NewsEmbeddingCache).filter(NewsEmbeddingCache.title_hash == title_hash).first()
                            if not exists:
                                cache_entry = NewsEmbeddingCache(
                                    news_id=item["id"],
                                    news_type=item["type"],
                                    title_hash=title_hash,
                                    embedding=json.dumps(new_embeddings[j])
                                )
                                db.add(cache_entry)
                        except Exception as e:
                            logger.error(f"Error caching embedding: {e}")
                try:
                    db.commit()
                except:
                    db.rollback()

    dim = 1536
    for i in range(len(embeddings)):
        if embeddings[i] is None:
            embeddings[i] = [0.0] * dim

    return embeddings

async def generate_cluster_title(cluster_items: List[dict]) -> str:
    """Generate an Arabic title for a news cluster using GPT-4o-mini"""
    if not OPENAI_API_KEY:
        return cluster_items[0]["title"][:100]

    try:
        titles_text = "\n".join([f"- {item['title']}" for item in cluster_items[:10]])
        prompt = f"""لديك مجموعة أخبار متشابهة تتحدث عن نفس الحدث:

{titles_text}

اكتب عنواناً واحداً قصيراً وجذاباً باللغة العربية يلخص الحدث المشترك. أجب بالعنوان فقط."""

        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "أنت محلل أخبار خبير. أجب بعنوان عربي قصير فقط بدون علامات تنصيص."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 200
        }

        response = await asyncio.to_thread(
            lambda: requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
        )

        if response.status_code == 200:
            result = response.json()
            title = result['choices'][0]['message']['content'].strip().strip('"').strip("'")
            return title
        return cluster_items[0]["title"][:100]
    except Exception as e:
        logger.error(f"Error generating cluster title: {e}")
        return cluster_items[0]["title"][:100]

# ============================================
# Persistent Cluster Storage & Incremental Assignment
# ============================================

def get_clusters_from_db(db):
    """Read stored clusters from database - fast path, no AI calls"""
    clusters = db.query(NewsCluster).all()
    if not clusters:
        return None

    all_members = db.query(NewsClusterMember).all()
    members_by_cluster = {}
    for m in all_members:
        members_by_cluster.setdefault(m.cluster_id, []).append(m)

    world_ids, yemen_ids, newspaper_ids = set(), set(), set()
    for members in members_by_cluster.values():
        for m in members:
            if m.news_type == 'world': world_ids.add(m.news_id)
            elif m.news_type == 'yemen': yemen_ids.add(m.news_id)
            else: newspaper_ids.add(m.news_id)

    world_map = {n.id: n for n in db.query(NewsItem).filter(NewsItem.id.in_(world_ids)).all()} if world_ids else {}
    yemen_map = {n.id: n for n in db.query(YemenNewsItem).filter(YemenNewsItem.id.in_(yemen_ids)).all()} if yemen_ids else {}
    newspaper_map = {n.id: n for n in db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id.in_(newspaper_ids)).all()} if newspaper_ids else {}

    result_clusters = []
    total_news = 0

    for cluster in clusters:
        members = members_by_cluster.get(cluster.id, [])
        if not members:
            continue

        news_items = []
        for m in members:
            n = None
            if m.news_type == 'world': n = world_map.get(m.news_id)
            elif m.news_type == 'yemen': n = yemen_map.get(m.news_id)
            else: n = newspaper_map.get(m.news_id)
            if n:
                news_items.append({
                    "id": n.id, "type": m.news_type, "title": n.title, "link": n.link,
                    "summary": n.summary, "source": n.source, "published": str(n.published),
                    "image_url": n.image_url, "video_id": getattr(n, 'video_id', None),
                    "is_important": getattr(n, 'is_important', 0),
                    "importance_reason": getattr(n, 'importance_reason', None)
                })

        if not news_items:
            continue

        items_sorted = sorted(news_items, key=lambda x: x["published"], reverse=True)
        sources = list(set(item["source"] for item in news_items))
        types_in_cluster = list(set(item["type"] for item in news_items))

        result_clusters.append({
            "id": cluster.id,
            "title": cluster.title,
            "is_event": bool(cluster.is_event),
            "news_count": len(news_items),
            "sources": sources,
            "source_count": len(sources),
            "types": types_in_cluster,
            "intensity": cluster.intensity or "important",
            "latest_date": items_sorted[0]["published"] if items_sorted else "",
            "news": items_sorted
        })
        total_news += len(news_items)

    #result_clusters.sort(key=lambda x: (x.get("is_event", False), x["news_count"]), reverse=True)
    result_clusters.sort(key=lambda x: ('yemen' in x.get('types', []), x.get("is_event", False), x["news_count"]), reverse=True)
    
    return {
        "clusters": result_clusters,
        "total_news": total_news,
        "total_clusters": len(result_clusters)
    }


def store_clusters_to_db(db, result_clusters, all_news, embeddings):
    """Store clustering results to DB with centroid embeddings for better matching"""
    try:
        item_embedding_map = {}
        for i, item in enumerate(all_news):
            item_embedding_map[(item["id"], item["type"])] = embeddings[i] if i < len(embeddings) else None

        for cluster_data in result_clusters:
            news_list = cluster_data.get("news", [])
            if not news_list:
                continue

            # Compute centroid (average) of all member embeddings for better topic representation
            member_embs = []
            for news_item in news_list:
                emb = item_embedding_map.get((news_item["id"], news_item["type"]))
                if emb and not all(v == 0.0 for v in emb):
                    member_embs.append(emb)

            centroid = None
            if member_embs:
                centroid = np.mean(np.array(member_embs), axis=0).tolist()

            cluster = NewsCluster(
                title=cluster_data["title"],
                intensity=cluster_data.get("intensity", "important"),
                is_event=1 if cluster_data.get("is_event", True) else 0,
                representative_embedding=json.dumps(centroid) if centroid else None
            )
            db.add(cluster)
            db.flush()

            for news_item in news_list:
                member = NewsClusterMember(
                    cluster_id=cluster.id,
                    news_id=news_item["id"],
                    news_type=news_item["type"]
                )
                db.add(member)

        db.commit()
        logger.info(f"[Clusters] Stored {len(result_clusters)} clusters to database")
    except Exception as e:
        db.rollback()
        logger.error(f"[Clusters] Error storing clusters to DB: {e}")


async def assign_news_to_cluster(db, news_id: int, news_title: str, news_summary: str, news_type: str):
    """Assign a new news item to the best matching cluster, or create a new one.
    Returns dict: {cluster_id, cluster_title, is_new_cluster, cluster_data (if new)} or None on error."""
    SIMILARITY_THRESHOLD = 0.38
    try:
        clusters = db.query(NewsCluster).all()
        if not clusters:
            logger.info(f"[Clusters] No clusters in DB yet, skipping assignment for {news_type}:{news_id}")
            return None

        item = {"id": news_id, "type": news_type, "title": news_title, "summary": news_summary or ""}
        new_embeddings = await get_embeddings_batch(db, [item])
        new_emb = new_embeddings[0]
        has_embedding = not all(v == 0.0 for v in new_emb)

        best_cluster = None
        best_sim = 0.0

        # Compare against cluster centroid embeddings
        if has_embedding:
            new_emb_np = np.array(new_emb)

            for c in clusters:
                if not c.representative_embedding:
                    continue
                try:
                    rep_emb = np.array(json.loads(c.representative_embedding))
                    dot = np.dot(new_emb_np, rep_emb)
                    norm = (np.linalg.norm(new_emb_np) * np.linalg.norm(rep_emb))
                    sim = float(dot / norm) if norm > 0 else 0.0
                    if sim > best_sim:
                        best_sim = sim
                        best_cluster = c
                except:
                    continue

            logger.info(f"[Clusters] Best match for '{news_title[:60]}': cluster '{best_cluster.title[:60] if best_cluster else 'None'}' sim={best_sim:.3f} (threshold={SIMILARITY_THRESHOLD})")

        if best_cluster and best_sim >= SIMILARITY_THRESHOLD:
            existing = db.query(NewsClusterMember).filter(
                NewsClusterMember.cluster_id == best_cluster.id,
                NewsClusterMember.news_id == news_id,
                NewsClusterMember.news_type == news_type
            ).first()
            if not existing:
                member = NewsClusterMember(cluster_id=best_cluster.id, news_id=news_id, news_type=news_type)
                db.add(member)
                best_cluster.updated_at = datetime.now()

                # Update centroid to include the new member
                if has_embedding and best_cluster.representative_embedding:
                    try:
                        old_centroid = np.array(json.loads(best_cluster.representative_embedding))
                        member_count = db.query(NewsClusterMember).filter(
                            NewsClusterMember.cluster_id == best_cluster.id
                        ).count()
                        new_centroid = ((old_centroid * (member_count - 1)) + new_emb_np) / member_count
                        best_cluster.representative_embedding = json.dumps(new_centroid.tolist())
                    except:
                        pass

                db.commit()
                logger.info(f"[Clusters] ✓ Assigned {news_type}:{news_id} to cluster #{best_cluster.id} '{best_cluster.title[:50]}' (sim={best_sim:.3f})")
                return {"cluster_id": best_cluster.id, "cluster_title": best_cluster.title, "is_new_cluster": False}

        # Try to match against topic clusters by keyword
        topic = identify_topic(news_title, news_summary or "")
        for c in clusters:
            if not c.is_event and c.title and topic in c.title:
                existing = db.query(NewsClusterMember).filter(
                    NewsClusterMember.cluster_id == c.id,
                    NewsClusterMember.news_id == news_id,
                    NewsClusterMember.news_type == news_type
                ).first()
                if not existing:
                    member = NewsClusterMember(cluster_id=c.id, news_id=news_id, news_type=news_type)
                    db.add(member)
                    c.updated_at = datetime.now()
                    db.commit()
                    logger.info(f"[Clusters] ✓ Assigned {news_type}:{news_id} to topic cluster '{c.title}' via topic '{topic}'")
                    return {"cluster_id": c.id, "cluster_title": c.title, "is_new_cluster": False}

        # No match found - create a new cluster
        intensity = classify_news_intensity(news_title)
        new_cluster = NewsCluster(
            title=news_title[:200],
            intensity=intensity,
            is_event=1,
            representative_embedding=json.dumps(new_emb) if has_embedding else None
        )
        db.add(new_cluster)
        db.flush()

        member = NewsClusterMember(
            cluster_id=new_cluster.id,
            news_id=news_id,
            news_type=news_type
        )
        db.add(member)
        db.commit()

        logger.info(f"[Clusters] ✓ Created new cluster #{new_cluster.id} for {news_type}:{news_id} '{news_title[:50]}'")
        return {
            "cluster_id": new_cluster.id,
            "cluster_title": new_cluster.title,
            "is_new_cluster": True,
            "cluster_data": {
                "id": new_cluster.id,
                "title": new_cluster.title,
                "is_event": True,
                "news_count": 1,
                "sources": [],
                "source_count": 0,
                "types": [news_type],
                "intensity": intensity,
                "latest_date": "",
                "news": []
            }
        }
    except Exception as e:
        logger.error(f"[Clusters] Error assigning news to cluster: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            db.rollback()
        except:
            pass
        return None


def fetch_newspaper_articles(source_url: str, source_name: str, last_article_ids: Optional[List[str]] = None) -> List[dict]:
    """Fetch NEW articles from a newspaper website"""
    articles = []
    last_article_ids_set = set(last_article_ids) if last_article_ids else set()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Connection': 'keep-alive',
    }
    
    try:
        response = requests.get(source_url, headers=headers, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all article links - different selectors for different sites
        article_links = []
        
        # Generic article selectors that work for most news sites
        selectors = [
            'article a[href]',
            'h2 a[href]', 'h3 a[href]', 'h4 a[href]',
            '.story a[href]', '.article a[href]',
            '.headline a[href]', '.title a[href]',
            '[data-testid="card"] a[href]',
            '.card a[href]', '.news-item a[href]',
            '.teaser a[href]', '.post a[href]',
            'a.storylink[href]', 'a.story-link[href]',
            '.article-title a[href]', '.entry-title a[href]',
        ]
        
        found_links = set()
        for selector in selectors:
            try:
                elements = soup.select(selector)
                for elem in elements:
                    href = elem.get('href')
                    if href:
                        # Make absolute URL
                        full_url = urljoin(source_url, href)
                        # Filter out non-article links
                        parsed = urlparse(full_url)
                        if (parsed.scheme in ['http', 'https'] and 
                            not any(x in full_url.lower() for x in ['/video/', '/videos/', '/live/', '/author/', '/tag/', '/category/', '/search/', '#', 'javascript:', 'mailto:'])):
                            if full_url not in found_links:
                                found_links.add(full_url)
                                # Get title from link text or parent element
                                title = elem.get_text(strip=True)
                                if not title or len(title) < 10:
                                    # Try to find title in parent elements
                                    parent = elem.parent
                                    for _ in range(3):
                                        if parent:
                                            h_tag = parent.find(['h1', 'h2', 'h3', 'h4'])
                                            if h_tag:
                                                title = h_tag.get_text(strip=True)
                                                break
                                            parent = parent.parent
                                
                                if title and len(title) >= 10:
                                    article_links.append({'url': full_url, 'title': title})
            except Exception:
                continue
        
        # Process found articles
        for article_data in article_links[:50]:  # Check up to 50 articles
            article_url = article_data['url']
            article_id = generate_article_id(article_url)
            
            # If we have last_article_ids, check if we've seen this article
            if last_article_ids_set and article_id in last_article_ids_set:
                logger.info(f"[Newspaper] Found known article {article_id[:8]} for {source_name}, stopping")
                break
            
            title = article_data['title']
            if not title or len(title) < 10:
                continue
            
            # Try to get image from the article page (optional, might slow down)
            image_url = None
            try:
                # Look for og:image in current page
                og_image = soup.find('meta', property='og:image')
                if og_image:
                    image_url = og_image.get('content')
            except:
                pass
            
            # Try to get a better summary from the specific article if possible
            # Note: In a production environment, we might want to do this asynchronously
            article_summary = f"مقال جديد من {source_name} يتناول آخر المستجدات الإخبارية. انقر لمتابعة التفاصيل والتحليلات الكاملة."
            
            # Translate Title and Summary
            translated_title = translate_to_arabic(title)
            translated_summary = translate_to_arabic(article_summary)
            
            articles.append({
                'article_id': article_id,
                'title': translated_title[:500],
                'link': article_url,
                'image_url': image_url,
                'source': source_name,
                'published': datetime.now(),
                'summary': translated_summary
            })
            
            # If no last_article_ids, we're in first run - collect first 5 articles
            if not last_article_ids_set and len(articles) >= 5:
                logger.info(f"[Newspaper] First run for {source_name}, collected 5 articles")
                break
        
    except Exception as e:
        logger.error(f"[Newspaper] Error fetching from {source_name}: {e}")
    
    return articles

async def fetch_all_newspaper_sources(db) -> List[dict]:
    """Fetch NEW articles from all newspaper sources in parallel with concurrency control"""
    
    # Get last 5 article IDs for each source
    source_last_articles = {}
    for source in NEWSPAPER_SOURCES:
        last_article_record = db.query(NewspaperLastArticle).filter(NewspaperLastArticle.source_name == source['name']).first()
        if last_article_record and last_article_record.last_article_ids:
            try:
                source_last_articles[source['name']] = json.loads(last_article_record.last_article_ids)
            except:
                source_last_articles[source['name']] = None
        else:
            source_last_articles[source['name']] = None
    
    semaphore = asyncio.Semaphore(3) # تقليل المهام المتوازية لترك موارد للنشر
    async def fetch_with_semaphore(source):
        async with semaphore:
            await pause_background_tasks.wait() # الانتظار إذا كان هناك نشر جاري
            last_article_ids = source_last_articles.get(source['name'])
            return await asyncio.to_thread(fetch_newspaper_articles, source['url'], source['name'], last_article_ids)

    tasks = [fetch_with_semaphore(source) for source in NEWSPAPER_SOURCES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine all results (skip exceptions)
    all_articles = []
    for idx, articles in enumerate(results):
        if isinstance(articles, Exception):
            logger.error(f"[Newspaper] Error in source fetch for {NEWSPAPER_SOURCES[idx]['name']}: {articles}")
            continue
        all_articles.extend(articles)
    
    # Sort by published date from NEWEST to OLDEST
    all_articles.sort(key=lambda x: x['published'], reverse=True)
    return all_articles

async def fetch_newspaper_feeds():
    """Main function to fetch and store ONLY NEW newspaper articles from all sources"""
    first_run = True
    while True:
        db = SessionLocal()
        new_items_found = []
        
        try:
            # Fetch ONLY NEW articles from all sources
            articles = await fetch_all_newspaper_sources(db)
            logger.info(f"[Newspaper] Found {len(articles)} NEW articles from all sources combined")
            
            # Group articles by source to track last 5 articles per source
            articles_by_source = {}
            for article in articles:
                source_name = article['source']
                if source_name not in articles_by_source:
                    articles_by_source[source_name] = []
                articles_by_source[source_name].append(article)
            
            # Add all new articles to database
            for article in articles:
                try:
                    # Check if article already exists (safety check)
                    exists = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.link == article['link']).first()
                    if exists:
                        logger.debug(f"[Newspaper] Article already exists: {article['link'][:50]}...")
                        continue
                    
                    new_item = NewspaperNewsItem(
                        title=article['title'],
                        link=article['link'],
                        summary=article.get('summary', ''),
                        published=article['published'],
                        source=article['source'],
                        image_url=article.get('image_url'),
                        article_id=article.get('article_id')
                    )
                    db.add(new_item)
                    db.commit()
                    db.refresh(new_item)  # Refresh to get the ID
                    
                    item_dict = {
                        "id": new_item.id,
                        "title": new_item.title,
                        "link": new_item.link,
                        "summary": new_item.summary,
                        "published": str(new_item.published),
                        "source": new_item.source,
                        "image_url": new_item.image_url,
                        "video_id": None,
                        "is_important": 0,
                        "importance_reason": None
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"[Newspaper] ✓ SAVED to DB (ID: {new_item.id}): {article['title'][:50]}... from {article['source']}")
                    
                    # Process event timeline only for updates (no longer automatic to save costs)
                    # if not first_run:
                    #     await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'newspaper')
                    #     cluster_result = await assign_news_to_cluster(db, new_item.id, new_item.title, new_item.summary or '', 'newspaper')
                    #     if cluster_result:
                    #         ws_type = "new_cluster_created" if cluster_result["is_new_cluster"] else "cluster_news_added"
                    #         ws_data = {"cluster_id": cluster_result["cluster_id"], "cluster_title": cluster_result["cluster_title"], "news": item_dict, "news_type": "newspaper"}
                    #         if cluster_result["is_new_cluster"]:
                    #             ws_data["cluster_data"] = cluster_result["cluster_data"]
                    #         await manager.broadcast(json.dumps({"type": ws_type, "data": ws_data}))
                    #         schedule_cluster_importance_reclassify(cluster_result["cluster_id"])
                except Exception as e:
                    db.rollback()
                    logger.error(f"[Newspaper] ✗ FAILED to save article: {article['title'][:50]}... Error: {e}")
            
            # Update last 5 articles for each source
            for source_name, source_articles in articles_by_source.items():
                if not source_articles:
                    continue
                
                last_article_record = db.query(NewspaperLastArticle).filter(NewspaperLastArticle.source_name == source_name).first()
                
                existing_ids = []
                if last_article_record and last_article_record.last_article_ids:
                    try:
                        existing_ids = json.loads(last_article_record.last_article_ids)
                    except:
                        existing_ids = []
                
                new_article_ids = [a['article_id'] for a in reversed(source_articles)]
                combined_ids = new_article_ids + existing_ids
                seen = set()
                unique_ids = []
                for art_id in combined_ids:
                    if art_id not in seen:
                        seen.add(art_id)
                        unique_ids.append(art_id)
                
                final_ids = unique_ids[:5]
                most_recent_article = source_articles[-1]
                
                if last_article_record:
                    last_article_record.last_article_ids = json.dumps(final_ids)
                    last_article_record.last_article_published = most_recent_article['published']
                    last_article_record.updated_at = datetime.now()
                    db.commit()
                    logger.info(f"[Newspaper] Updated last {len(final_ids)} articles for {source_name}")
                else:
                    last_article_record = NewspaperLastArticle(
                        source_name=source_name,
                        last_article_ids=json.dumps(final_ids),
                        last_article_published=most_recent_article['published']
                    )
                    db.add(last_article_record)
                    db.commit()
                    logger.info(f"[Newspaper] Set initial {len(final_ids)} articles for {source_name}")
        
        except Exception as e:
            logger.error(f"[Newspaper] Error in fetch_newspaper_feeds: {e}")
        
        # Broadcast new items
        if new_items_found:
            logger.info(f"[Newspaper] Broadcasting {len(new_items_found)} new articles")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_newspaper_news", "data": item}))
        
        db.close()
        first_run = False
        
        # Check every 20 minutes for newspapers (less frequent than YouTube)
        logger.info("[Newspaper] Waiting 20 minutes before next fetch...")
        await asyncio.sleep(1200)


def fetch_youtube_channel_videos(channel_url: str, channel_name: str, last_video_ids: Optional[List[str]] = None, is_playlist: bool = False) -> List[dict]:
    """Fetch NEW videos from a YouTube channel/playlist - only videos newer than any in last_video_ids (last 5)"""
    videos = []
    last_video_ids_set = set(last_video_ids) if last_video_ids else set()
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': 50,
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(channel_url, download=False)
                if info and 'entries' in info:
                    entries_list = list(info['entries']) if info['entries'] else []
                    for entry in entries_list:
                        if entry:
                            video_id = entry.get('id')
                            if not video_id:
                                continue
                            if last_video_ids_set and video_id in last_video_ids_set:
                                logger.info(f"Found known video {video_id} for {channel_name}, stopping")
                                break
                            
                            title = entry.get('title', 'No Title')
                            if not title or title == '[Private video]' or title == '[Deleted video]':
                                continue
                                
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                            
                            upload_date = entry.get('upload_date') or entry.get('release_date')
                            if upload_date:
                                try:
                                    published = datetime.strptime(upload_date, '%Y%m%d')
                                except:
                                    published = datetime.now()
                            else:
                                timestamp = entry.get('timestamp') or entry.get('release_timestamp')
                                if timestamp:
                                    try:
                                        published = datetime.fromtimestamp(timestamp)
                                    except:
                                        published = datetime.now()
                                else:
                                    published = datetime.now()
                            
                            videos.append({
                                'video_id': video_id,
                                'title': translate_to_arabic(title),
                                'link': url,
                                'image_url': thumbnail,
                                'source': channel_name,
                                'published': published,
                                'summary': translate_to_arabic(f"فيديو جديد من {channel_name}")
                            })
                            
                            if not last_video_ids_set and len(videos) >= 5:
                                logger.info(f"First run for {channel_name}, collected 5 videos")
                                break
            except Exception as e:
                logger.error(f"Error extracting info from {channel_name}: {e}")
                if not is_playlist:
                    try:
                        match = re.search(r'/@([^/]+)', channel_url)
                        if match:
                            handle = match.group(1)
                            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={handle}"
                            response = requests.get(rss_url, timeout=10)
                            if response.status_code == 200:
                                from xml.etree import ElementTree as ET
                                from dateutil import parser
                                root = ET.fromstring(response.content)
                                for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry')[:50]:
                                    v_id_elem = entry.find('{http://www.youtube.com/xml/schemas/2015}videoId')
                                    if v_id_elem is None: continue
                                    v_id = v_id_elem.text
                                    
                                    if last_video_ids_set and v_id in last_video_ids_set:
                                        break
                                    
                                    t_elem = entry.find('{http://www.w3.org/2005/Atom}title')
                                    t = t_elem.text if t_elem is not None else 'No Title'
                                    l_elem = entry.find('{http://www.w3.org/2005/Atom}link')
                                    l = l_elem.get('href') if l_elem is not None else f"https://www.youtube.com/watch?v={v_id}"
                                    p_elem = entry.find('{http://www.w3.org/2005/Atom}published')
                                    p_text = p_elem.text if p_elem is not None else None
                                    
                                    try:
                                        pub = parser.parse(p_text) if p_text else datetime.now()
                                    except:
                                        pub = datetime.now()
                                    
                                    videos.append({
                                        'video_id': v_id,
                                        'title': translate_to_arabic(t),
                                        'link': l,
                                        'image_url': f"https://img.youtube.com/vi/{v_id}/maxresdefault.jpg",
                                        'source': channel_name,
                                        'published': pub,
                                        'summary': translate_to_arabic(f"فيديو جديد من {channel_name}")
                                    })
                                    if not last_video_ids_set and len(videos) >= 5:
                                        break
                    except Exception as e2:
                        logger.error(f"RSS fallback also failed for {channel_name}: {e2}")
    except Exception as e:
        logger.error(f"Error fetching YouTube channel {channel_name}: {e}")
    
    return videos

def get_google_youtube_ranking(query: str, limit: int = 10) -> List[str]:
    """Search Google for YouTube videos using the user's preferred pattern"""
    from urllib.parse import unquote
    try:
        cached = _get_cached_rank_result("google", query)
        if cached is not None:
            return cached[:limit]

        if _should_skip_google_for_title(query):
            return []

        if not _acquire_google_request_slot():
            logger.warning(f"[Google] Cooldown active, skipping query: '{query[:80]}'")
            return []

        # Use the specific pattern requested by the user
        search_query = f"https://youtube.com {query}"
        encoded_query = quote(search_query)
        url = f"https://www.google.com/search?q={encoded_query}&num={limit*2}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/",
            "DNT": "1"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        _register_google_response(response.status_code)
        if response.status_code != 200:
            if response.status_code == 429:
                with _google_rate_lock:
                    retry_after = int(max(1, _google_rate_state["blocked_until"] - time.time()))
                logger.error(f"[Google] Error 429 for '{query}' - cooling down ~{retry_after}s")
            else:
                logger.error(f"[Google] Error {response.status_code} for '{query}'")
            return []
            
        soup = BeautifulSoup(response.text, 'html.parser')
        video_ids = []
        
        # Look for any link that contains a youtube video ID
        for a in soup.find_all('a', href=True):
            href = a['href']
            
            # Google sometimes wraps links in /url?q=
            if "/url?q=" in href:
                try:
                    href = unquote(href.split("/url?q=")[1].split("&")[0])
                except:
                    pass
            
            # Broad matching for various youtube URL formats
            # Patterns: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/v/ID, etc.
            match = re.search(r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})', href)
            if match:
                vid_id = match.group(1)
                if vid_id not in video_ids:
                    video_ids.append(vid_id)
                    if len(video_ids) >= limit:
                        break
        
        if video_ids:
            logger.info(f"[Google] Found {len(video_ids)} videos for '{query}': {video_ids[:3]}")
        _set_cached_rank_result("google", query, video_ids)
        return video_ids
    except Exception as e:
        logger.error(f"[Google] Exception for '{query}': {e}")
    return []

def get_youtube_search_results(query: str, limit: int = 10) -> List[str]:
    """Search YouTube for a query and return top video IDs (Google/YouTube's ranking)"""
    try:
        cached = _get_cached_rank_result("youtube", query)
        if cached is not None:
            return cached[:limit]

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': limit,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # ytsearch: prefix allows searching
            search_url = f"ytsearch{limit}:{query}"
            info = ydl.extract_info(search_url, download=False)
            if info and 'entries' in info:
                ids = [entry.get('id') for entry in info['entries'] if entry and entry.get('id')]
                _set_cached_rank_result("youtube", query, ids)
                return ids
    except Exception as e:
        logger.error(f"Error in YouTube search for '{query}': {e}")
    return []

def _tokenize_for_match(text: str) -> Set[str]:
    cleaned = clean_news_text(text or "")
    tokens = [t for t in re.split(r"\s+", cleaned) if len(t) >= 2]
    return set(tokens)

def _text_overlap_score(query: str, candidate: str) -> float:
    q = _tokenize_for_match(query)
    c = _tokenize_for_match(candidate)
    if not q or not c:
        return 0.0
    inter = len(q.intersection(c))
    return inter / max(1, len(q))

async def _classify_single_cluster_payload(cluster: dict) -> int:
    """Classify important/suggested items inside one cluster and persist flags."""
    candidate_members = [
        m for m in cluster["news"]
        if m.get("type") in ("world", "yemen", "newspaper")
    ]
    if not candidate_members:
        return 0

    cluster_title = cluster["title"]
    max_picks = 3 if len(candidate_members) >= 6 else 2
    youtube_members = [
        m for m in candidate_members
        if m.get("video_id") and m.get("type") in ("world", "yemen")
    ]
    score_map: Dict[str, Dict] = {}

    # PHASE 1: Google ranking (primary)
    if youtube_members:
        try:
            google_video_ids = await asyncio.to_thread(get_google_youtube_ranking, cluster_title, 20)
            if google_video_ids:
                for rank, vid_id in enumerate(google_video_ids):
                    match = next((m for m in youtube_members if m.get("video_id") == vid_id), None)
                    if not match:
                        continue
                    key = f'{match["type"]}:{match["id"]}'
                    current = score_map.get(key, {
                        "id": match["id"],
                        "type": match["type"],
                        "score": 0.0,
                        "reasons": []
                    })
                    current["score"] += 1.25 / (rank + 1)
                    current["reasons"].append(f"ترتيب جوجل #{rank+1}")
                    score_map[key] = current
        except Exception as e:
            logger.error(f"[Classify] Google search error for '{cluster_title}': {e}")

    # PHASE 2: YouTube ranking
    if youtube_members:
        try:
            yt_video_ids = await asyncio.to_thread(get_youtube_search_results, cluster_title, 20)
            if yt_video_ids:
                for rank, vid_id in enumerate(yt_video_ids):
                    match = next((m for m in youtube_members if m.get("video_id") == vid_id), None)
                    if not match:
                        continue
                    key = f'{match["type"]}:{match["id"]}'
                    current = score_map.get(key, {
                        "id": match["id"],
                        "type": match["type"],
                        "score": 0.0,
                        "reasons": []
                    })
                    current["score"] += 1.0 / (rank + 1)
                    current["reasons"].append(f"ترتيب يوتيوب #{rank+1}")
                    score_map[key] = current
        except Exception as e:
            logger.error(f"[Classify] YouTube search error for '{cluster_title}': {e}")

    # PHASE 3: Local relevance fallback
    if not score_map:
        for match in candidate_members:
            overlap = _text_overlap_score(cluster_title, match.get("title", ""))
            if overlap <= 0:
                continue
            key = f'{match["type"]}:{match["id"]}'
            score_map[key] = {
                "id": match["id"],
                "type": match["type"],
                "score": overlap,
                "reasons": [f"تشابه عنوان {overlap:.2f}"]
            }

    # Guarantee at least one suggestion if cluster has members
    if not score_map:
        newest = sorted(candidate_members, key=lambda x: x.get("published", ""), reverse=True)[0]
        fallback_key = f'{newest["type"]}:{newest["id"]}'
        score_map[fallback_key] = {
            "id": newest["id"],
            "type": newest["type"],
            "score": 0.01,
            "reasons": ["أحدث فيديو في المجموعة"]
        }

    ranked = sorted(score_map.values(), key=lambda x: x["score"], reverse=True)
    selected = ranked[:max_picks]

    inner_db = SessionLocal()
    try:
        world_ids = [m["id"] for m in candidate_members if m["type"] == "world"]
        yemen_ids = [m["id"] for m in candidate_members if m["type"] == "yemen"]
        newspaper_ids = [m["id"] for m in candidate_members if m["type"] == "newspaper"]

        if world_ids:
            inner_db.query(NewsItem).filter(NewsItem.id.in_(world_ids)).update({
                "is_important": 0,
                "importance_reason": None
            }, synchronize_session=False)
        if yemen_ids:
            inner_db.query(YemenNewsItem).filter(YemenNewsItem.id.in_(yemen_ids)).update({
                "is_important": 0,
                "importance_reason": None
            }, synchronize_session=False)
        if newspaper_ids:
            inner_db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id.in_(newspaper_ids)).update({
                "is_important": 0,
                "importance_reason": None
            }, synchronize_session=False)

        updated = 0
        for item in selected:
            reason = " | ".join(item["reasons"][:2])
            if item["type"] == "world":
                inner_db.query(NewsItem).filter(NewsItem.id == item["id"]).update({
                    "is_important": 1,
                    "importance_reason": reason
                }, synchronize_session=False)
                updated += 1
            elif item["type"] == "yemen":
                inner_db.query(YemenNewsItem).filter(YemenNewsItem.id == item["id"]).update({
                    "is_important": 1,
                    "importance_reason": reason
                }, synchronize_session=False)
                updated += 1
            elif item["type"] == "newspaper":
                inner_db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id == item["id"]).update({
                    "is_important": 1,
                    "importance_reason": reason
                }, synchronize_session=False)
                updated += 1

        inner_db.commit()
        return updated
    except Exception as e:
        logger.error(f"Error updating cluster {cluster_title}: {e}")
        inner_db.rollback()
        return 0
    finally:
        inner_db.close()

async def classify_cluster_by_id(cluster_id: int) -> int:
    """Run important-video classification for one cluster."""
    db = SessionLocal()
    try:
        clusters_data = get_clusters_from_db(db)
        if not clusters_data or not clusters_data.get("clusters"):
            return 0
        target = next((c for c in clusters_data["clusters"] if c.get("id") == cluster_id), None)
        if not target:
            return 0
    finally:
        db.close()

    updated = await _classify_single_cluster_payload(target)
    if updated > 0:
        _cluster_cache["data"] = None
    return updated

async def fetch_all_youtube_channels(db) -> List[dict]:
    """Fetch NEW videos from all YouTube channels/playlists in parallel, sorted from oldest to newest"""
    
    # Get last 5 video IDs for each channel
    channel_last_videos = {}
    for channel in YOUTUBE_CHANNELS:
        last_video_record = db.query(ChannelLastVideo).filter(ChannelLastVideo.channel_name == channel['name']).first()
        if last_video_record and last_video_record.last_video_ids:
            try:
                # Parse JSON array of last 5 video IDs
                channel_last_videos[channel['name']] = json.loads(last_video_record.last_video_ids)
            except:
                channel_last_videos[channel['name']] = None
        else:
            channel_last_videos[channel['name']] = None
    
    semaphore = asyncio.Semaphore(3)
    async def fetch_with_semaphore(channel):
        async with semaphore:
            await pause_background_tasks.wait() # الانتظار إذا كان هناك نشر جاري
            last_video_ids = channel_last_videos.get(channel['name'])
            is_playlist = channel.get('type') == 'playlist'
            return await asyncio.to_thread(fetch_youtube_channel_videos, channel['url'], channel['name'], last_video_ids, is_playlist)

    tasks = [fetch_with_semaphore(channel) for channel in YOUTUBE_CHANNELS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine all results (skip exceptions)
    all_videos = []
    for idx, videos in enumerate(results):
        if isinstance(videos, Exception):
            logger.error(f"Error in channel fetch for {YOUTUBE_CHANNELS[idx]['name']}: {videos}")
            continue
        all_videos.extend(videos)
    
    # Sort by published date from NEWEST to OLDEST (newest first - across all channels)
    all_videos.sort(key=lambda x: x['published'], reverse=True)
    return all_videos

async def fetch_all_yemen_youtube_channels(db) -> List[dict]:
    """Fetch NEW videos from all Yemen YouTube channels, filtered for Yemen-related content"""
    
    # Get last 5 video IDs for each channel
    channel_last_videos = {}
    for channel in YEMEN_YOUTUBE_CHANNELS:
        last_video_record = db.query(YemenChannelLastVideo).filter(YemenChannelLastVideo.channel_name == channel['name']).first()
        if last_video_record and last_video_record.last_video_ids:
            try:
                channel_last_videos[channel['name']] = json.loads(last_video_record.last_video_ids)
            except:
                channel_last_videos[channel['name']] = None
        else:
            channel_last_videos[channel['name']] = None
    
    semaphore = asyncio.Semaphore(3)
    async def fetch_with_semaphore(channel):
        async with semaphore:
            await pause_background_tasks.wait() # الانتظار إذا كان هناك نشر جاري
            last_video_ids = channel_last_videos.get(channel['name'])
            is_playlist = channel.get('type') == 'playlist'
            return await asyncio.to_thread(fetch_youtube_channel_videos, channel['url'], channel['name'], last_video_ids, is_playlist)

    tasks = [fetch_with_semaphore(channel) for channel in YEMEN_YOUTUBE_CHANNELS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine all results and filter for Yemen-related content
    all_videos = []
    for idx, videos in enumerate(results):
        if isinstance(videos, Exception):
            logger.error(f"[Yemen] Error in channel fetch for {YEMEN_YOUTUBE_CHANNELS[idx]['name']}: {videos}")
            continue
        # Filter videos to only include Yemen-related content
        for video in videos:
            if is_yemen_related(video['title']):
                video['summary'] = f"فيديو جديد من {video['source']} - أخبار اليمن"
                all_videos.append(video)
                logger.info(f"[Yemen] Found Yemen-related video: {video['title'][:50]}...")
    
    # Sort by published date from NEWEST to OLDEST
    all_videos.sort(key=lambda x: x['published'], reverse=True)
    return all_videos

async def fetch_youtube_feeds():
    """Main function to fetch and store ONLY NEW YouTube videos from all channels"""
    first_run = True
    while True:
        db = SessionLocal()
        new_items_found = []
        
        try:

            # Fetch ONLY NEW videos from all channels (using last_video_ids tracking)
            videos = await fetch_all_youtube_channels(db)
            logger.info(f"Found {len(videos)} NEW videos from all channels combined")
            
            # Group videos by channel to track last 5 videos per channel
            videos_by_channel = {}
            for video in videos:
                channel_name = video['source']
                if channel_name not in videos_by_channel:
                    videos_by_channel[channel_name] = []
                videos_by_channel[channel_name].append(video)
            
            # Add all new videos to database
            for video in videos:
                try:
                    # Check if video already exists (safety check)
                    exists = db.query(NewsItem).filter(NewsItem.link == video['link']).first()
                    if exists:
                        continue
                    
                    new_item = NewsItem(
                        title=video['title'],
                        link=video['link'],
                        summary=video.get('summary', ''),
                        published=video['published'],
                        source=video['source'],
                        image_url=video.get('image_url'),
                        video_id=video.get('video_id')
                    )
                    db.add(new_item)
                    db.commit()
                    db.refresh(new_item)
                    
                    item_dict = {
                        "id": new_item.id,
                        "title": new_item.title,
                        "link": new_item.link,
                        "summary": new_item.summary,
                        "published": str(new_item.published),
                        "source": new_item.source,
                        "image_url": new_item.image_url,
                        "video_id": new_item.video_id,
                        "is_important": getattr(new_item, 'is_important', 0),
                        "importance_reason": getattr(new_item, 'importance_reason', None)
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"✓ SAVED to DB (ID: {new_item.id}): {video['title'][:50]}... from {video['source']}")
                    
                    # Process event timeline only for updates (no longer automatic to save costs)
                    # if not first_run:
                    #     await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'world')
                    #     cluster_result = await assign_news_to_cluster(db, new_item.id, new_item.title, new_item.summary or '', 'world')
                    #     if cluster_result:
                    #         ws_type = "new_cluster_created" if cluster_result["is_new_cluster"] else "cluster_news_added"
                    #         ws_data = {"cluster_id": cluster_result["cluster_id"], "cluster_title": cluster_result["cluster_title"], "news": item_dict, "news_type": "world"}
                    #         if cluster_result["is_new_cluster"]:
                    #             ws_data["cluster_data"] = cluster_result["cluster_data"]
                    #         await manager.broadcast(json.dumps({"type": ws_type, "data": ws_data}))
                    #         schedule_cluster_importance_reclassify(cluster_result["cluster_id"])
                except Exception as e:
                    db.rollback()
                    logger.error(f"✗ FAILED to save video: {video['title'][:50]}... Error: {e}")
            
            # Update last 5 videos for each channel
            for channel_name, channel_videos in videos_by_channel.items():
                if not channel_videos:
                    continue
                
                # Get existing record
                last_video_record = db.query(ChannelLastVideo).filter(ChannelLastVideo.channel_name == channel_name).first()
                
                # Get existing last video IDs
                existing_ids = []
                if last_video_record and last_video_record.last_video_ids:
                    try:
                        existing_ids = json.loads(last_video_record.last_video_ids)
                    except:
                        existing_ids = []
                
                # Add new video IDs to the beginning (newest first)
                # Since videos are sorted oldest to newest, reverse them to get newest first
                new_video_ids = [v['video_id'] for v in reversed(channel_videos)]
                
                # Combine: new videos + existing videos, keep only first 5
                combined_ids = new_video_ids + existing_ids
                # Remove duplicates while preserving order
                seen = set()
                unique_ids = []
                for vid_id in combined_ids:
                    if vid_id not in seen:
                        seen.add(vid_id)
                        unique_ids.append(vid_id)
                
                # Keep only last 5
                final_ids = unique_ids[:5]
                
                # Get the most recent video's publish date
                most_recent_video = channel_videos[-1]  # Last in list = newest (since sorted oldest to newest)
                
                if last_video_record:
                    # Update existing record
                    last_video_record.last_video_ids = json.dumps(final_ids)
                    last_video_record.last_video_published = most_recent_video['published']
                    last_video_record.updated_at = datetime.now()
                    db.commit()
                    logger.info(f"Updated last {len(final_ids)} videos for {channel_name}")
                else:
                    # Create new record
                    last_video_record = ChannelLastVideo(
                        channel_name=channel_name,
                        last_video_ids=json.dumps(final_ids),
                        last_video_published=most_recent_video['published']
                    )
                    db.add(last_video_record)
                    db.commit()
                    logger.info(f"Set initial {len(final_ids)} videos for {channel_name}")
        
        except Exception as e:
            logger.error(f"Error in fetch_youtube_feeds: {e}")
        
        # Broadcast new items (always broadcast if there are new items)
        if new_items_found:
            logger.info(f"Broadcasting {len(new_items_found)} new videos")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_news", "data": item}))
        
        db.close()
        first_run = False
        
        # Check every 5 minutes as requested
        logger.info("Waiting 3 minutes before next fetch...")
        await asyncio.sleep(180)

async def fetch_yemen_youtube_feeds():
    """Main function to fetch and store ONLY NEW Yemen-related YouTube videos"""
    first_run = True
    while True:
        db = SessionLocal()
        new_items_found = []
        
        try:
            # Fetch ONLY NEW videos from all Yemen channels (filtered for Yemen content)
            videos = await fetch_all_yemen_youtube_channels(db)
            logger.info(f"[Yemen] Found {len(videos)} NEW Yemen-related videos from all channels combined")
            
            # Group videos by channel to track last 5 videos per channel
            videos_by_channel = {}
            for video in videos:
                channel_name = video['source']
                if channel_name not in videos_by_channel:
                    videos_by_channel[channel_name] = []
                videos_by_channel[channel_name].append(video)
            
            # Add all new videos to database
            for video in videos:
                try:
                    # Check if video already exists (safety check)
                    exists = db.query(YemenNewsItem).filter(YemenNewsItem.link == video['link']).first()
                    if exists:
                        continue
                    
                    new_item = YemenNewsItem(
                        title=video['title'],
                        link=video['link'],
                        summary=video.get('summary', ''),
                        published=video['published'],
                        source=video['source'],
                        image_url=video.get('image_url'),
                        video_id=video.get('video_id')
                    )
                    db.add(new_item)
                    db.commit()
                    db.refresh(new_item)
                    
                    item_dict = {
                        "id": new_item.id,
                        "title": new_item.title,
                        "link": new_item.link,
                        "summary": new_item.summary,
                        "published": str(new_item.published),
                        "source": new_item.source,
                        "image_url": new_item.image_url,
                        "video_id": new_item.video_id,
                        "is_important": getattr(new_item, 'is_important', 0),
                        "importance_reason": getattr(new_item, 'importance_reason', None)
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"[Yemen] ✓ SAVED to DB (ID: {new_item.id}): {video['title'][:50]}... from {video['source']}")
                    
                    # Process event timeline only for updates (no longer automatic to save costs)
                    # if not first_run:
                    #     await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'yemen')
                    #     cluster_result = await assign_news_to_cluster(db, new_item.id, new_item.title, new_item.summary or '', 'yemen')
                    #     if cluster_result:
                    #         ws_type = "new_cluster_created" if cluster_result["is_new_cluster"] else "cluster_news_added"
                    #         ws_data = {"cluster_id": cluster_result["cluster_id"], "cluster_title": cluster_result["cluster_title"], "news": item_dict, "news_type": "yemen"}
                    #         if cluster_result["is_new_cluster"]:
                    #             ws_data["cluster_data"] = cluster_result["cluster_data"]
                    #         await manager.broadcast(json.dumps({"type": ws_type, "data": ws_data}))
                    #         schedule_cluster_importance_reclassify(cluster_result["cluster_id"])
                except Exception as e:
                    db.rollback()
                    logger.error(f"[Yemen] ✗ FAILED to save video: {video['title'][:50]}... Error: {e}")
            
            # Update last 5 videos for each channel (track ALL fetched videos, not just Yemen-related)
            # We need to update tracking for all channels even if their videos weren't Yemen-related
            for channel in YEMEN_YOUTUBE_CHANNELS:
                channel_name = channel['name']
                channel_videos = videos_by_channel.get(channel_name, [])
                
                if not channel_videos:
                    continue
                
                last_video_record = db.query(YemenChannelLastVideo).filter(YemenChannelLastVideo.channel_name == channel_name).first()
                
                existing_ids = []
                if last_video_record and last_video_record.last_video_ids:
                    try:
                        existing_ids = json.loads(last_video_record.last_video_ids)
                    except:
                        existing_ids = []
                
                new_video_ids = [v['video_id'] for v in reversed(channel_videos)]
                combined_ids = new_video_ids + existing_ids
                seen = set()
                unique_ids = []
                for vid_id in combined_ids:
                    if vid_id not in seen:
                        seen.add(vid_id)
                        unique_ids.append(vid_id)
                
                final_ids = unique_ids[:5]
                most_recent_video = channel_videos[-1]
                
                if last_video_record:
                    last_video_record.last_video_ids = json.dumps(final_ids)
                    last_video_record.last_video_published = most_recent_video['published']
                    last_video_record.updated_at = datetime.now()
                    db.commit()
                else:
                    last_video_record = YemenChannelLastVideo(
                        channel_name=channel_name,
                        last_video_ids=json.dumps(final_ids),
                        last_video_published=most_recent_video['published']
                    )
                    db.add(last_video_record)
                    db.commit()
        
        except Exception as e:
            logger.error(f"[Yemen] Error in fetch_yemen_youtube_feeds: {e}")
        
        # Broadcast new Yemen items
        if new_items_found:
            logger.info(f"[Yemen] Broadcasting {len(new_items_found)} new Yemen videos")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_yemen_news", "data": item}))
        
        db.close()
        first_run = False
        
        # Check every 5 minutes
        logger.info("[Yemen] Waiting 20 minutes before next fetch...")
        await asyncio.sleep(1200)

async def fetch_all_dubbed_youtube_channels(db) -> List[dict]:
    """Fetch NEW videos from all Dubbed YouTube channels"""
    
    channel_last_videos = {}
    for channel in DUBBED_YOUTUBE_CHANNELS:
        last_video_record = db.query(DubbedChannelLastVideo).filter(DubbedChannelLastVideo.channel_name == channel['name']).first()
        if last_video_record and last_video_record.last_video_ids:
            try:
                channel_last_videos[channel['name']] = json.loads(last_video_record.last_video_ids)
            except:
                channel_last_videos[channel['name']] = None
        else:
            channel_last_videos[channel['name']] = None
    
    semaphore = asyncio.Semaphore(3)
    async def fetch_with_semaphore(channel):
        async with semaphore:
            await pause_background_tasks.wait()
            last_video_ids = channel_last_videos.get(channel['name'])
            is_playlist = channel.get('type') == 'playlist'
            return await asyncio.to_thread(fetch_youtube_channel_videos, channel['url'], channel['name'], last_video_ids, is_playlist)

    tasks = [fetch_with_semaphore(channel) for channel in DUBBED_YOUTUBE_CHANNELS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_videos = []
    for idx, videos in enumerate(results):
        if isinstance(videos, Exception):
            logger.error(f"[Dubbed] Error in channel fetch for {DUBBED_YOUTUBE_CHANNELS[idx]['name']}: {videos}")
            continue
        all_videos.extend(videos)
    
    all_videos.sort(key=lambda x: x['published'], reverse=True)
    return all_videos

async def fetch_dubbed_youtube_feeds():
    """Main function to fetch and store ONLY NEW Dubbed YouTube videos"""
    first_run = True
    while True:
        db = SessionLocal()
        new_items_found = []
        
        try:
            videos = await fetch_all_dubbed_youtube_channels(db)
            logger.info(f"[Dubbed] Found {len(videos)} NEW Dubbed videos from all channels combined")
            
            videos_by_channel = {}
            for video in videos:
                channel_name = video['source']
                if channel_name not in videos_by_channel:
                    videos_by_channel[channel_name] = []
                videos_by_channel[channel_name].append(video)
            
            for video in videos:
                try:
                    exists = db.query(DubbedNewsItem).filter(DubbedNewsItem.link == video['link']).first()
                    if exists:
                        continue
                    
                    new_item = DubbedNewsItem(
                        title=video['title'],
                        link=video['link'],
                        summary=video.get('summary', ''),
                        published=video['published'],
                        source=video['source'],
                        image_url=video.get('image_url'),
                        video_id=video.get('video_id')
                    )
                    db.add(new_item)
                    db.commit()
                    db.refresh(new_item)
                    
                    item_dict = {
                        "id": new_item.id,
                        "title": new_item.title,
                        "link": new_item.link,
                        "summary": new_item.summary,
                        "published": str(new_item.published),
                        "source": new_item.source,
                        "image_url": new_item.image_url,
                        "video_id": new_item.video_id,
                        "is_important": getattr(new_item, 'is_important', 0),
                        "importance_reason": getattr(new_item, 'importance_reason', None)
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"[Dubbed] ✓ SAVED to DB (ID: {new_item.id}): {video['title'][:50]}... from {video['source']}")
                except Exception as e:
                    db.rollback()
                    logger.error(f"[Dubbed] ✗ FAILED to save video: {video['title'][:50]}... Error: {e}")
            
            for channel in DUBBED_YOUTUBE_CHANNELS:
                channel_name = channel['name']
                channel_videos = videos_by_channel.get(channel_name, [])
                
                if not channel_videos:
                    continue
                
                last_video_record = db.query(DubbedChannelLastVideo).filter(DubbedChannelLastVideo.channel_name == channel_name).first()
                
                existing_ids = []
                if last_video_record and last_video_record.last_video_ids:
                    try:
                        existing_ids = json.loads(last_video_record.last_video_ids)
                    except:
                        existing_ids = []
                
                new_video_ids = [v['video_id'] for v in reversed(channel_videos)]
                combined_ids = new_video_ids + existing_ids
                seen = set()
                unique_ids = []
                for vid_id in combined_ids:
                    if vid_id not in seen:
                        seen.add(vid_id)
                        unique_ids.append(vid_id)
                
                final_ids = unique_ids[:5]
                most_recent_video = channel_videos[-1]
                
                if last_video_record:
                    last_video_record.last_video_ids = json.dumps(final_ids)
                    last_video_record.last_video_published = most_recent_video['published']
                    last_video_record.updated_at = datetime.now()
                    db.commit()
                else:
                    last_video_record = DubbedChannelLastVideo(
                        channel_name=channel_name,
                        last_video_ids=json.dumps(final_ids),
                        last_video_published=most_recent_video['published']
                    )
                    db.add(last_video_record)
                    db.commit()
        
        except Exception as e:
            logger.error(f"[Dubbed] Error in fetch_dubbed_youtube_feeds: {e}")
        
        if new_items_found:
            logger.info(f"[Dubbed] Broadcasting {len(new_items_found)} new Dubbed videos")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_dubbed_news", "data": item}))
        
        db.close()
        first_run = False
        
        logger.info("[Dubbed] Waiting 5 minutes before next fetch...")
        await asyncio.sleep(300)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_youtube_feeds())
    asyncio.create_task(fetch_yemen_youtube_feeds())
    asyncio.create_task(fetch_newspaper_feeds())
    asyncio.create_task(fetch_dubbed_youtube_feeds())

@app.get("/api/news")
async def get_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    # Order by created_at DESC (newest added first) and id DESC as tie-breaker
    news = db.query(NewsItem).order_by(desc(NewsItem.created_at), desc(NewsItem.id)).offset(skip).limit(limit).all()
    total = db.query(NewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/yemen-news")
async def get_yemen_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    # Order by created_at DESC (newest added first) and id DESC as tie-breaker
    news = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.created_at), desc(YemenNewsItem.id)).offset(skip).limit(limit).all()
    total = db.query(YemenNewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/dubbed-news")
async def get_dubbed_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    news = db.query(DubbedNewsItem).order_by(desc(DubbedNewsItem.created_at), desc(DubbedNewsItem.id)).offset(skip).limit(limit).all()
    total = db.query(DubbedNewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.post("/api/process-news-ai/{news_type}/{news_id}")
async def process_news_ai(news_type: str, news_id: int):
    """Manually trigger AI processing for a news item (Timeline and Evolution) to save costs."""
    db = SessionLocal()
    try:
        # Get the news item to ensure it exists and get its info
        news_item = None
        if news_type == 'world':
            news_item = db.query(NewsItem).filter(NewsItem.id == news_id).first()
        elif news_type == 'yemen':
            news_item = db.query(YemenNewsItem).filter(YemenNewsItem.id == news_id).first()
        elif news_type == 'newspaper':
            news_item = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id == news_id).first()
        
        if not news_item:
            return {"error": "News item not found"}, 404
            
        logger.info(f"Manual AI processing triggered for {news_type}:{news_id}")
        
        # 1. Process Timeline
        await process_event_timeline(db, news_id, news_item.title, news_item.summary or '', news_type)
        
        # 2. Assign to Cluster (Event Evolution)
        cluster_result = await assign_news_to_cluster(db, news_id, news_item.title, news_item.summary or '', news_type)
        
        # 3. Handle cluster results (WebSocket broadcast)
        if cluster_result:
            item_dict = {
                "id": news_item.id,
                "title": news_item.title,
                "link": news_item.link,
                "summary": news_item.summary,
                "published": str(news_item.published),
                "source": news_item.source,
                "image_url": news_item.image_url,
                "video_id": getattr(news_item, 'video_id', None),
                "is_important": getattr(news_item, 'is_important', 0),
                "importance_reason": getattr(news_item, 'importance_reason', None)
            }
            ws_type = "new_cluster_created" if cluster_result["is_new_cluster"] else "cluster_news_added"
            ws_data = {"cluster_id": cluster_result["cluster_id"], "cluster_title": cluster_result["cluster_title"], "news": item_dict, "news_type": news_type}
            if cluster_result["is_new_cluster"]:
                ws_data["cluster_data"] = cluster_result["cluster_data"]
            await manager.broadcast(json.dumps({"type": ws_type, "data": ws_data}))
            schedule_cluster_importance_reclassify(cluster_result["cluster_id"])
            
        return {
            "status": "success", 
            "message": "AI processing complete", 
            "timeline_processed": True,
            "cluster_info": cluster_result
        }
    except Exception as e:
        logger.error(f"Error in manual AI processing: {e}")
        return {"error": str(e)}, 500
    finally:
        db.close()

@app.get("/api/newspaper-news")
async def get_newspaper_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    # Order by created_at DESC (newest added first) and id DESC as tie-breaker
    news = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.created_at), desc(NewspaperNewsItem.id)).offset(skip).limit(limit).all()
    total = db.query(NewspaperNewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/recommended-news")
async def get_recommended_news(page: int = 1, limit: int = 20):
    """Return only suggested/important items across world, yemen, and newspaper."""
    db = SessionLocal()
    try:
        take = max(limit * 4, 60)
        world_items = db.query(NewsItem).filter(NewsItem.is_important == 1).order_by(
            desc(NewsItem.created_at), desc(NewsItem.id)
        ).limit(take).all()
        yemen_items = db.query(YemenNewsItem).filter(YemenNewsItem.is_important == 1).order_by(
            desc(YemenNewsItem.created_at), desc(YemenNewsItem.id)
        ).limit(take).all()
        newspaper_items = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.is_important == 1).order_by(
            desc(NewspaperNewsItem.created_at), desc(NewspaperNewsItem.id)
        ).limit(take).all()

        all_items = []
        for n in world_items:
            all_items.append({
                "id": n.id, "type": "world", "title": n.title, "link": n.link,
                "summary": n.summary, "published": str(n.published), "source": n.source,
                "image_url": n.image_url, "video_id": n.video_id,
                "is_important": n.is_important, "importance_reason": n.importance_reason
            })
        for n in yemen_items:
            all_items.append({
                "id": n.id, "type": "yemen", "title": n.title, "link": n.link,
                "summary": n.summary, "published": str(n.published), "source": n.source,
                "image_url": n.image_url, "video_id": n.video_id,
                "is_important": n.is_important, "importance_reason": n.importance_reason
            })
        for n in newspaper_items:
            all_items.append({
                "id": n.id, "type": "newspaper", "title": n.title, "link": n.link,
                "summary": n.summary, "published": str(n.published), "source": n.source,
                "image_url": n.image_url, "video_id": None,
                "is_important": getattr(n, 'is_important', 0),
                "importance_reason": getattr(n, 'importance_reason', None)
            })

        all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
        total = len(all_items)
        skip = (page - 1) * limit
        paged = all_items[skip: skip + limit]
        return {"items": paged, "total": total, "page": page, "limit": limit}
    finally:
        db.close()

@app.get("/api/recommended-index")
async def get_recommended_index():
    """Lightweight index of suggested items for fast UI badge sync."""
    db = SessionLocal()
    try:
        rows = []
        for n in db.query(NewsItem.id, NewsItem.importance_reason).filter(NewsItem.is_important == 1).all():
            rows.append({"type": "world", "id": n.id, "importance_reason": n.importance_reason})
        for n in db.query(YemenNewsItem.id, YemenNewsItem.importance_reason).filter(YemenNewsItem.is_important == 1).all():
            rows.append({"type": "yemen", "id": n.id, "importance_reason": n.importance_reason})
        for n in db.query(NewspaperNewsItem.id, NewspaperNewsItem.importance_reason).filter(NewspaperNewsItem.is_important == 1).all():
            rows.append({"type": "newspaper", "id": n.id, "importance_reason": n.importance_reason})
        return {"items": rows, "total": len(rows)}
    finally:
        db.close()

@app.get("/api/event-timeline/{news_type}/{news_id}")
async def get_event_timeline(news_type: str, news_id: int):
    """Get the event timeline for a specific news item - includes ALL related news from all types"""
    db = SessionLocal()
    try:
        # Get all related news through event threads (no filter on news_type for related items)
        threads = db.query(EventThread).filter(
            EventThread.news_id == news_id,
            EventThread.news_type == news_type
        ).all()
        
        # Also get threads where this news is a related item (reverse lookup)
        # Check both when related_news_type matches and when it's the same type (legacy data)
        reverse_threads = db.query(EventThread).filter(
            EventThread.related_news_id == news_id
        ).filter(
            (EventThread.related_news_type == news_type) | 
            ((EventThread.related_news_type == None) & (EventThread.news_type == news_type))
        ).all()
        
        # Combine all related news with their types
        # Format: (id, type)
        related_items = set()
        thread_title = ""
        similarity_reason = ""
        
        for thread in threads:
            # Use related_news_type if available, otherwise fall back to news_type
            related_type = thread.related_news_type or thread.news_type
            related_items.add((thread.related_news_id, related_type))
            if thread.thread_title:
                thread_title = thread.thread_title
            if thread.similarity_reason:
                similarity_reason = thread.similarity_reason
        
        for thread in reverse_threads:
            related_items.add((thread.news_id, thread.news_type))
            if thread.thread_title and not thread_title:
                thread_title = thread.thread_title
            if thread.similarity_reason and not similarity_reason:
                similarity_reason = thread.similarity_reason
        
        if not related_items:
            return {
                "thread_title": "",
                "related_news": [],
                "reason": "",
                "current_news_id": news_id
            }
        
        # Get the actual news items from their respective tables
        related_news = []
        
        for rid, rtype in related_items:
            try:
                if rtype == 'world':
                    news_item = db.query(NewsItem).filter(NewsItem.id == rid).first()
                elif rtype == 'yemen':
                    news_item = db.query(YemenNewsItem).filter(YemenNewsItem.id == rid).first()
                elif rtype == 'newspaper':
                    news_item = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id == rid).first()
                elif rtype == 'dubbed':
                    news_item = db.query(DubbedNewsItem).filter(DubbedNewsItem.id == rid).first()
                
                if news_item:
                    related_news.append({
                        "id": news_item.id,
                        "title": news_item.title,
                        "link": news_item.link,
                        "summary": news_item.summary,
                        "published": str(news_item.published),
                        "source": news_item.source,
                        "image_url": news_item.image_url,
                        "video_id": getattr(news_item, 'video_id', None),
                        "is_important": getattr(news_item, 'is_important', 0),
                        "importance_reason": getattr(news_item, 'importance_reason', None),
                        "news_type": rtype  # Include the type for reference
                    })
            except Exception as e:
                logger.error(f"Error fetching related news {rtype}:{rid}: {e}")
                continue
        
        # Sort by published date (oldest first for timeline)
        related_news.sort(key=lambda x: x['published'])
        
        return {
            "thread_title": thread_title,
            "related_news": related_news,
            "reason": similarity_reason,
            "current_news_id": news_id
        }
    finally:
        db.close()

@app.get("/api/heatmap")
async def get_heatmap_data():
    """Get geopolitical heatmap data - aggregated news locations with intensity"""
    db = SessionLocal()
    try:
        # Get all news from all tables
        world_news = db.query(NewsItem).order_by(desc(NewsItem.created_at)).limit(200).all()
        yemen_news = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.created_at)).limit(200).all()
        newspaper_news = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.created_at)).limit(200).all()
        dubbed_news = db.query(DubbedNewsItem).order_by(desc(DubbedNewsItem.created_at)).limit(200).all()
        
        # Combine all news items
        all_items = []
        for n in world_news:
            all_items.append({
                "id": n.id, "title": n.title, "link": n.link,
                "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "type": "world"
            })
        for n in yemen_news:
            all_items.append({
                "id": n.id, "title": n.title, "link": n.link,
                "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "type": "yemen"
            })
        for n in newspaper_news:
            all_items.append({
                "id": n.id, "title": n.title, "link": n.link,
                "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "type": "newspaper"
            })
        for n in dubbed_news:
            all_items.append({
                "id": n.id, "title": n.title, "link": n.link,
                "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "type": "dubbed"
            })
        
        # Process each item and aggregate by country
        locations = {}
        for item in all_items:
            found_countries = extract_locations_from_title(item["title"])
            intensity = classify_news_intensity(item["title"])
            
            for country_key in found_countries:
                if country_key not in locations:
                    geo = COUNTRY_DATA[country_key]
                    locations[country_key] = {
                        "country": geo["country"],
                        "country_en": geo["country_en"],
                        "lat": geo["lat"],
                        "lng": geo["lng"],
                        "news_count": 0,
                        "intensity": "important",
                        "news": []
                    }
                
                locations[country_key]["news_count"] += 1
                locations[country_key]["news"].append({
                    "id": item["id"],
                    "title": item["title"],
                    "link": item["link"],
                    "source": item["source"],
                    "published": item["published"],
                    "type": item["type"]
                })
                
                # Upgrade intensity to the highest level found
                current_intensity = locations[country_key]["intensity"]
                if INTENSITY_RANK.get(intensity, 0) > INTENSITY_RANK.get(current_intensity, 0):
                    locations[country_key]["intensity"] = intensity
        
        return {
            "locations": list(locations.values()),
            "total_news": len(all_items),
            "mapped_countries": len(locations)
        }
    finally:
        db.close()

@app.get("/api/news/clusters")
async def get_news_clusters(rebuild: bool = False):
    """Cluster news - reads from DB if available, otherwise builds and stores.
    Pass ?rebuild=true to force rebuild with updated centroid embeddings."""

    if rebuild:
        logger.info("[Clusters] Force rebuild requested - clearing stored clusters")
        db_clear = SessionLocal()
        try:
            db_clear.query(NewsClusterMember).delete()
            db_clear.query(NewsCluster).delete()
            db_clear.commit()
        finally:
            db_clear.close()
    else:
        # Fast path: read persisted clusters from database
        db_read = SessionLocal()
        try:
            stored = get_clusters_from_db(db_read)
            if stored and stored["total_clusters"] > 0:
                return stored
        finally:
            db_read.close()

    # No stored clusters (or rebuild) - build from scratch using existing algorithm
    db = SessionLocal()
    try:
        world_news = db.query(NewsItem).order_by(desc(NewsItem.created_at)).limit(250).all()
        yemen_news = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.created_at)).limit(200).all()
        newspaper_news = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.created_at)).limit(200).all()
        dubbed_news = db.query(DubbedNewsItem).order_by(desc(DubbedNewsItem.created_at)).limit(200).all()

        all_news = []
        for n in world_news:
            all_news.append({
                "id": n.id, "type": "world", "title": n.title, "link": n.link,
                "summary": n.summary, "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "video_id": n.video_id, 
                "is_important": n.is_important, "importance_reason": n.importance_reason
            })
        for n in yemen_news:
            all_news.append({
                "id": n.id, "type": "yemen", "title": n.title, "link": n.link,
                "summary": n.summary, "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "video_id": n.video_id,
                "is_important": n.is_important, "importance_reason": n.importance_reason
            })
        for n in newspaper_news:
            all_news.append({
                "id": n.id, "type": "newspaper", "title": n.title, "link": n.link,
                "summary": n.summary, "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "video_id": None,
                "is_important": getattr(n, 'is_important', 0),
                "importance_reason": getattr(n, 'importance_reason', None)
            })
        for n in dubbed_news:
            all_news.append({
                "id": n.id, "type": "dubbed", "title": n.title, "link": n.link,
                "summary": n.summary, "source": n.source, "published": str(n.published),
                "image_url": n.image_url, "video_id": n.video_id,
                "is_important": getattr(n, 'is_important', 0),
                "importance_reason": getattr(n, 'importance_reason', None)
            })

        if len(all_news) < 2:
            return {"clusters": [], "total_news": len(all_news), "total_clusters": 0}

        embeddings = await get_embeddings_batch(db, all_news)

        all_zero = all(all(v == 0.0 for v in emb) for emb in embeddings)
        if all_zero:
            logger.warning("All embeddings are zero vectors")
            labels = [-1] * len(all_news)
        else:
            try:
                from sklearn.cluster import AgglomerativeClustering
                from sklearn.metrics.pairwise import cosine_distances

                embedding_matrix = np.array(embeddings)
                distance_matrix = cosine_distances(embedding_matrix)

                clustering = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=0.45,
                    metric="precomputed",
                    linkage="average"
                )
                labels = clustering.fit_predict(distance_matrix)
            except ImportError:
                labels = [-1] * len(all_news)

        cluster_groups = {}
        singletons = []
        
        for i, label in enumerate(labels):
            label_int = int(label)
            if label_int == -1:
                singletons.append(all_news[i])
                continue
            if label_int not in cluster_groups:
                cluster_groups[label_int] = []
            cluster_groups[label_int].append(all_news[i])

        final_clusters_data = []
        actual_singletons = []
        
        for label, items in cluster_groups.items():
            if len(items) >= 2:
                final_clusters_data.append(items)
            else:
                actual_singletons.extend(items)
        actual_singletons.extend(singletons)

        topic_groups = {}
        for item in actual_singletons:
            topic = identify_topic(item["title"], item.get("summary", ""))
            if topic not in topic_groups:
                topic_groups[topic] = []
            topic_groups[topic].append(item)

        result_clusters = []
        
        for i, items in enumerate(final_clusters_data):
            try:
                title = await generate_cluster_title(items)
            except:
                title = items[0]["title"][:100]

            sources = list(set(item["source"] for item in items))
            types_in_cluster = list(set(item["type"] for item in items))
            items_sorted = sorted(items, key=lambda x: x["published"], reverse=True)
            intensity = classify_news_intensity(items[0]["title"])
            
            result_clusters.append({
                "id": f"event_{i}",
                "title": title,
                "is_event": True,
                "news_count": len(items),
                "sources": sources,
                "source_count": len(sources),
                "types": types_in_cluster,
                "intensity": intensity,
                "latest_date": items_sorted[0]["published"] if items_sorted else "",
                "news": items_sorted
            })

        for topic, items in topic_groups.items():
            if not items: continue
            items_sorted = sorted(items, key=lambda x: x["published"], reverse=True)
            sources = list(set(item["source"] for item in items))
            types_in_cluster = list(set(item["type"] for item in items))
            
            result_clusters.append({
                "id": f"topic_{topic}",
                "title": f"ملخص: {topic}",
                "is_event": False,
                "news_count": len(items),
                "sources": sources,
                "source_count": len(sources),
                "types": types_in_cluster,
                "intensity": "important",
                "latest_date": items_sorted[0]["published"] if items_sorted else "",
                "news": items_sorted
            })

        result_clusters.sort(key=lambda x: (x.get("is_event", False), x["news_count"]), reverse=True)

        # Persist clusters to database for fast future retrieval
        store_clusters_to_db(db, result_clusters, all_news, embeddings)

        # Read back from DB to get consistent integer IDs
        stored = get_clusters_from_db(db)
        if stored:
            logger.info(f"[Clusters] Built & stored {stored['total_clusters']} clusters from {len(all_news)} news items")
            return stored

        result = {
            "clusters": result_clusters,
            "total_news": len(all_news),
            "total_clusters": len(result_clusters)
        }
        logger.info(f"[Clusters] Built {len(result_clusters)} clusters from {len(all_news)} news items")
        return result
    except Exception as e:
        logger.error(f"Error in get_news_clusters: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"clusters": [], "total_news": 0, "total_clusters": 0, "error": str(e)}
    finally:
        db.close()

@app.get("/api/clusters/test-match")
async def test_cluster_match(title: str = "", summary: str = ""):
    """Debug: test which cluster a title would match against"""
    if not title:
        return {"error": "provide ?title=..."}
    db = SessionLocal()
    try:
        clusters = db.query(NewsCluster).all()
        if not clusters:
            return {"message": "No clusters in DB yet", "clusters_count": 0}

        item = {"id": 0, "type": "test", "title": title, "summary": summary}
        embeddings = await get_embeddings_batch(db, [item])
        new_emb = embeddings[0]
        has_embedding = not all(v == 0.0 for v in new_emb)

        if not has_embedding:
            return {"message": "Could not generate embedding", "has_embedding": False}

        new_emb_np = np.array(new_emb)
        results = []
        for c in clusters:
            if not c.representative_embedding:
                continue
            try:
                rep_emb = np.array(json.loads(c.representative_embedding))
                dot = np.dot(new_emb_np, rep_emb)
                norm = (np.linalg.norm(new_emb_np) * np.linalg.norm(rep_emb))
                sim = float(dot / norm) if norm > 0 else 0.0
                member_count = db.query(NewsClusterMember).filter(NewsClusterMember.cluster_id == c.id).count()
                results.append({
                    "cluster_id": c.id,
                    "cluster_title": c.title[:100],
                    "similarity": round(sim, 4),
                    "is_event": bool(c.is_event),
                    "member_count": member_count,
                    "would_match": sim >= 0.38
                })
            except:
                continue

        results.sort(key=lambda x: x["similarity"], reverse=True)
        topic = identify_topic(title, summary)
        return {
            "input_title": title,
            "detected_topic": topic,
            "clusters_count": len(clusters),
            "threshold": 0.38,
            "top_matches": results[:10]
        }
    finally:
        db.close()

@app.get("/api/debug")
async def debug_info():
    """Debug endpoint to check database status"""
    db = SessionLocal()
    try:
        world_news_count = db.query(NewsItem).count()
        yemen_news_count = db.query(YemenNewsItem).count()
        newspaper_news_count = db.query(NewspaperNewsItem).count()
        dubbed_news_count = db.query(DubbedNewsItem).count()
        world_channels_count = db.query(ChannelLastVideo).count()
        yemen_channels_count = db.query(YemenChannelLastVideo).count()
        dubbed_channels_count = db.query(DubbedChannelLastVideo).count()
        newspaper_sources_count = db.query(NewspaperLastArticle).count()
        
        # Get latest news items
        latest_world = db.query(NewsItem).order_by(desc(NewsItem.created_at)).limit(3).all()
        latest_yemen = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.created_at)).limit(3).all()
        latest_newspaper = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.created_at)).limit(3).all()
        
        return {
            "database_path": DB_PATH,
            "data_dir": DATA_DIR,
            "database_exists": os.path.exists(DB_PATH),
            "database_size_kb": round(os.path.getsize(DB_PATH) / 1024, 2) if os.path.exists(DB_PATH) else 0,
            "counts": {
                "world_news": world_news_count,
                "yemen_news": yemen_news_count,
                "newspaper_news": newspaper_news_count,
                "dubbed_news": dubbed_news_count,
                "world_channels_tracked": world_channels_count,
                "yemen_channels_tracked": yemen_channels_count,
                "dubbed_channels_tracked": dubbed_channels_count,
                "newspaper_sources_tracked": newspaper_sources_count
            },
            "latest_world_news": [{"title": n.title[:50], "published": str(n.published), "source": n.source} for n in latest_world],
            "latest_yemen_news": [{"title": n.title[:50], "published": str(n.published), "source": n.source} for n in latest_yemen],
            "latest_newspaper_news": [{"title": n.title[:50], "published": str(n.published), "source": n.source} for n in latest_newspaper],
            "active_websocket_connections": len(manager.active_connections)
        }
    finally:
        db.close()

@app.post("/api/clear-all")
async def clear_all_news():
    """Clear all news items and tracking data from the database"""
    db = SessionLocal()
    try:
        db.query(NewsItem).delete()
        db.query(YemenNewsItem).delete()
        db.query(NewspaperNewsItem).delete()
        db.query(DubbedNewsItem).delete()
        db.query(ChannelLastVideo).delete()
        db.query(YemenChannelLastVideo).delete()
        db.query(DubbedChannelLastVideo).delete()
        db.query(NewspaperLastArticle).delete()
        db.query(EventThread).delete()
        db.query(NewsEmbeddingCache).delete()
        db.query(NewsClusterMember).delete()
        db.query(NewsCluster).delete()
        db.commit()
        _cluster_cache["data"] = None
        _cluster_cache["timestamp"] = None
        logger.info("Manual database clear performed. All news and tracking data deleted.")
        return {"message": "All news and tracking data have been cleared successfully."}
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing database: {e}")
        return {"error": str(e)}, 500
    finally:
        db.close()

_cluster_classify_tasks: Dict[int, asyncio.Task] = {}
AUTO_CLASSIFY_DEBOUNCE_SECONDS = 4

def schedule_cluster_importance_reclassify(cluster_id: int):
    """Debounced background classifier per cluster to avoid duplicate heavy work."""
    try:
        cluster_id = int(cluster_id)
    except Exception:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    active = _cluster_classify_tasks.get(cluster_id)
    if active and not active.done():
        return

    async def _runner():
        try:
            await asyncio.sleep(AUTO_CLASSIFY_DEBOUNCE_SECONDS)
            updated = await classify_cluster_by_id(cluster_id)
            if updated > 0:
                await manager.broadcast(json.dumps({
                    "type": "cluster_importance_updated",
                    "data": {"cluster_id": cluster_id, "updated_count": updated}
                }))
        except Exception as e:
            logger.error(f"[Classify] background auto-classify failed for cluster {cluster_id}: {e}")
        finally:
            _cluster_classify_tasks.pop(cluster_id, None)

    _cluster_classify_tasks[cluster_id] = loop.create_task(_runner())

@app.get("/api/clusters/classify")
async def classify_clusters(db: Session = Depends(get_db)):
    """Analyze clusters and flag top important videos based on Google/YouTube ranking + local relevance."""
    try:
        # 1. Get all clusters and their members
        clusters_data = get_clusters_from_db(db)
        if not clusters_data or not clusters_data.get("clusters"):
            return {"message": "No clusters to classify", "count": 0}
            
        # 2. Define a worker function for parallel processing
        semaphore = asyncio.Semaphore(6)

        async def process_single_cluster(cluster):
            async with semaphore:
                return await _classify_single_cluster_payload(cluster)

        # 3. Run all cluster processing tasks in parallel (limited by semaphore)
        tasks = [process_single_cluster(cluster) for cluster in clusters_data["clusters"]]
        results = await asyncio.gather(*tasks)
        classified_count = sum(results)
        
        # Clear cache
        _cluster_cache["data"] = None
        
        return {
            "message": f"تم الانتهاء من التصنيف. تم تحديد {classified_count} فيديوهات مهمة داخل المجموعات.",
            "count": classified_count,
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Error in classify_clusters endpoint: {e}")
        return {"error": str(e)}, 500

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            try:
                # Wait for message with timeout (25 seconds)
                # This allows us to send ping if no activity
                message = await asyncio.wait_for(websocket.receive_text(), timeout=25.0)
                # If client sends "pong", just acknowledge it
                if message == "pong":
                    continue
            except asyncio.TimeoutError:
                # No message received, send ping to keep connection alive
                try:
                    await websocket.send_text('{"type": "ping"}')
                except:
                    break
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Serve static files
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

if os.path.exists(static_dir):
    app.mount("/dist", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def read_index():
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Please create index.html in public folder"}

    @app.get("/{path:path}")
    async def serve_static(path: str):
        file_path = os.path.join(static_dir, path)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return FileResponse(file_path)
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "File not found"}
