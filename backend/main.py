import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import json
import re
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
import yt_dlp
import requests
from bs4 import BeautifulSoup
import hashlib
from urllib.parse import urljoin, urlparse, quote
import html

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup - Use /data for Railway Volume persistence
import os
DATA_DIR = os.environ.get('DATA_DIR', '/data' if os.path.exists('/data') else '.')
DB_PATH = os.path.join(DATA_DIR, 'world_news.db')
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
logger.info(f"Using database at: {DB_PATH}")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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
    created_at = Column(DateTime, default=datetime.now) # Track when added to our DB

class YemenChannelLastVideo(Base):
    __tablename__ = "yemen_channel_last_video"
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

            # Check for yemen_news columns
            result = conn.execute(text("PRAGMA table_info(yemen_news)"))
            yemen_columns = [row[1] for row in result]
            if 'created_at' not in yemen_columns:
                logger.info("Adding created_at column to yemen_news table...")
                conn.execute(text("ALTER TABLE yemen_news ADD COLUMN created_at DATETIME"))
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
            
            # Check if newspaper_last_article table exists
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='newspaper_last_article'"))
            if not result.fetchone():
                logger.info("Creating newspaper_last_article table...")
                NewspaperLastArticle.__table__.create(engine)
                logger.info("Successfully created newspaper_last_article table")
            
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
    """Process and store event timeline for a new news item - excluding Yemen news as requested"""
    if news_type == 'yemen':
        return
        
    try:
        # Get news from specified types to find related ones (Excluding Yemen news)
        world_news = db.query(NewsItem).order_by(desc(NewsItem.published)).limit(150).all()
        newspaper_news = db.query(NewspaperNewsItem).order_by(desc(NewspaperNewsItem.published)).limit(150).all()
        
        # Prepare combined news list with type prefix to identify source
        all_news_combined = []
        
        for n in world_news:
            if not (news_type == 'world' and n.id == news_id):
                all_news_combined.append({"id": f"world:{n.id}", "title": n.title, "published": n.published, "type": "world", "real_id": n.id})
        
        for n in newspaper_news:
            if not (news_type == 'newspaper' and n.id == news_id):
                all_news_combined.append({"id": f"newspaper:{n.id}", "title": n.title, "published": n.published, "type": "newspaper", "real_id": n.id})
        
        if not all_news_combined:
            return
            
        # Sort ALL news by published date DESC so AI sees the most recent ones first across ALL sources
        all_news_combined.sort(key=lambda x: x.get('published') or datetime.min, reverse=True)
        
        # Find related news using AI (searches across all types)
        result = await find_related_news_with_ai(news_title, news_summary, all_news_combined, news_type)
        
        if result.get("thread_title") and result.get("related_ids"):
            # Store the event threads
            for related_id_str in result["related_ids"]:
                try:
                    # Parse the type:id format
                    if isinstance(related_id_str, str) and ':' in related_id_str:
                        related_type, related_id_val = related_id_str.split(':', 1)
                        related_id = int(related_id_val)
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
        
        prompt = f"""أنت محلل أخبار خبير مهمتك الربط بين الأخبار ذات الصلة المباشرة فقط لتكوين "خريطة زمنية" أو "خيط أحداث" (Event Thread).
        
الخبر الحالي الذي نريد البحث عن أخبار مرتبطة به:
العنوان: {current_news_title}
الملخص: {current_news_summary}

قائمة الأخبار المتاحة للربط (مرتبة من الأحدث):
{news_list_text}

المطلوب بدقة:
1. اختر فقط الأخبار التي تتحدث عن **نفس الحدث تحديداً** أو تعتبر **تطوراً مباشراً** له. لا تربط أخباراً لمجرد أنها في نفس الدولة أو نفس التصنيف العام.
2. أعطني عنواناً عربياً قصيراً ومركزاً جداً يصف هذا "الخيط" (مثال: "تفاقم أزمة غزة"، "مفاوضات وقف إطلاق النار").
3. أرجع قائمة بـ الـ IDs الكاملة (كما هي في القائمة أعلاه، مثلاً 'world:123') للأخبار المرتبطة (بحد أقصى 10 أخبار).
4. اشرح باختصار شديد سبب الربط.

يجب أن تكون الإجابة بصيغة JSON فقط كالتالي:
{{
    "thread_title": "عنوان الخيط",
    "related_ids": ["world:12", "yemen:5"],
    "reason": "سبب الترابط"
}}

إذا لم تجد أي خبر مرتبط بنفس الموضوع تماماً، أرجع قائمة فارغة:
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
    {"url": "https://www.youtube.com/@WION/videos", "name": "WION", "type": "channel"},
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

def translate_to_arabic(text: str) -> str:
    """Translate English text to Arabic using Google Translate free API"""
    if not text or any(char in text for char in 'أبتثجحخدذرزسشصضطظعغفقكلمنهوي'): # Skip if already has Arabic chars
        return text
    
    try:
        # Using the unofficial but widely used Google Translate API endpoint
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=ar&dt=t&q={quote(text)}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            result = response.json()
            translated_text = "".join([segment[0] for segment in result[0] if segment[0]])
            return translated_text
        return text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

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
    """Fetch NEW articles from all newspaper sources in parallel"""
    
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
    
    # Create tasks for all sources
    tasks = []
    for source in NEWSPAPER_SOURCES:
        last_article_ids = source_last_articles.get(source['name'])
        if last_article_ids:
            logger.info(f"[Newspaper] Checking {source['name']} for new articles (last {len(last_article_ids)} IDs tracked)...")
        else:
            logger.info(f"[Newspaper] Checking {source['name']} for new articles (first run)...")
        tasks.append(asyncio.to_thread(fetch_newspaper_articles, source['url'], source['name'], last_article_ids))
    
    # Run all tasks in parallel
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
                        "image_url": new_item.image_url
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"[Newspaper] ✓ SAVED to DB (ID: {new_item.id}): {article['title'][:50]}... from {article['source']}")
                    
                    # Process event timeline only for updates (not first run)
                    if not first_run:
                        await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'newspaper')
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

def fetch_youtube_channel_videos(channel_url: str, channel_name: str, last_video_ids: Optional[List[str]] = None, is_playlist: bool = False) -> List[dict]:
    """Fetch NEW videos from a YouTube channel/playlist - only videos newer than any in last_video_ids (last 5)"""
    videos = []
    
    # Convert to set for faster lookup
    last_video_ids_set = set(last_video_ids) if last_video_ids else set()
    
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': 50,  # Check up to 50 videos
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(channel_url, download=False)
                
                if info and 'entries' in info:
                    entries_list = list(info['entries']) if info['entries'] else []
                    
                    # For playlists, videos might be in reverse order (oldest first), so we need to handle this
                    # For channels/videos tabs, newest videos are typically first
                    
                    for entry in entries_list:
                        if entry:
                            video_id = entry.get('id')
                            if not video_id:
                                continue
                            
                            # If we have last_video_ids, stop when we find ANY of them (videos come newest first for channels)
                            if last_video_ids_set and video_id in last_video_ids_set:
                                logger.info(f"Found known video {video_id} for {channel_name}, stopping")
                                break
                            
                            title = entry.get('title', 'No Title')
                            if not title or title == '[Private video]' or title == '[Deleted video]':
                                continue
                                
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            
                            # Get thumbnail
                            thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                            
                            # Get upload date - try multiple fields
                            upload_date = entry.get('upload_date') or entry.get('release_date')
                            if upload_date:
                                try:
                                    published = datetime.strptime(upload_date, '%Y%m%d')
                                except:
                                    published = datetime.now()
                            else:
                                # Try timestamp
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
                            
                            # If no last_video_ids, we're in first run - collect first 5 videos
                            if not last_video_ids_set and len(videos) >= 5:
                                logger.info(f"First run for {channel_name}, collected 5 videos")
                                break
                                
            except Exception as e:
                logger.error(f"Error extracting info from {channel_name}: {e}")
                # Fallback: Try RSS method for channels only (not playlists)
                if not is_playlist:
                    try:
                        # Extract channel handle
                        match = re.search(r'/@([^/]+)', channel_url)
                        if match:
                            handle = match.group(1)
                            # Try RSS feed
                            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={handle}"
                            import requests
                            from xml.etree import ElementTree as ET
                            from dateutil import parser
                            
                            response = requests.get(rss_url, timeout=10)
                            if response.status_code == 200:
                                root = ET.fromstring(response.content)
                                for entry in root.findall('.//{http://www.w3.org/2005/Atom}entry')[:50]:
                                    video_id_elem = entry.find('{http://www.youtube.com/xml/schemas/2015}videoId')
                                    if video_id_elem is None:
                                        continue
                                    video_id = video_id_elem.text
                                    
                                    # If we have last_video_ids, stop when we find ANY of them
                                    if last_video_ids_set and video_id in last_video_ids_set:
                                        logger.info(f"Found known video {video_id} for {channel_name} (RSS), stopping")
                                        break
                                    
                                    title_elem = entry.find('{http://www.w3.org/2005/Atom}title')
                                    title = title_elem.text if title_elem is not None else 'No Title'
                                    
                                    link_elem = entry.find('{http://www.w3.org/2005/Atom}link')
                                    link = link_elem.get('href') if link_elem is not None else f"https://www.youtube.com/watch?v={video_id}"
                                    
                                    published_elem = entry.find('{http://www.w3.org/2005/Atom}published')
                                    published_text = published_elem.text if published_elem is not None else None
                                    
                                    try:
                                        published = parser.parse(published_text) if published_text else datetime.now()
                                    except:
                                        published = datetime.now()
                                    
                                    thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                                    
                                    videos.append({
                                        'video_id': video_id,
                                        'title': translate_to_arabic(title),
                                        'link': link,
                                        'image_url': thumbnail,
                                        'source': channel_name,
                                        'published': published,
                                        'summary': translate_to_arabic(f"فيديو جديد من {channel_name}")
                                    })
                                    
                                    # If no last_video_ids, we're in first run - collect first 5 videos
                                    if not last_video_ids_set and len(videos) >= 5:
                                        break
                    except Exception as e2:
                        logger.error(f"RSS fallback also failed for {channel_name}: {e2}")
        
    except Exception as e:
        logger.error(f"Error fetching YouTube channel {channel_name}: {e}")
    
    return videos

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
    
    # Create tasks for all channels
    tasks = []
    for channel in YOUTUBE_CHANNELS:
        last_video_ids = channel_last_videos.get(channel['name'])
        is_playlist = channel.get('type') == 'playlist'
        if last_video_ids:
            logger.info(f"Checking {channel['name']} for new videos (last {len(last_video_ids)} IDs tracked)...")
        else:
            logger.info(f"Checking {channel['name']} for new videos (first run)...")
        tasks.append(asyncio.to_thread(fetch_youtube_channel_videos, channel['url'], channel['name'], last_video_ids, is_playlist))
    
    # Run all tasks in parallel
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
    
    # Create tasks for all channels
    tasks = []
    for channel in YEMEN_YOUTUBE_CHANNELS:
        last_video_ids = channel_last_videos.get(channel['name'])
        is_playlist = channel.get('type') == 'playlist'
        if last_video_ids:
            logger.info(f"[Yemen] Checking {channel['name']} for new videos (last {len(last_video_ids)} IDs tracked)...")
        else:
            logger.info(f"[Yemen] Checking {channel['name']} for new videos (first run)...")
        tasks.append(asyncio.to_thread(fetch_youtube_channel_videos, channel['url'], channel['name'], last_video_ids, is_playlist))
    
    # Run all tasks in parallel
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
                        "image_url": new_item.image_url
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"✓ SAVED to DB (ID: {new_item.id}): {video['title'][:50]}... from {video['source']}")
                    
                    # Process event timeline only for updates (not first run)
                    if not first_run:
                        await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'world')
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
                        "image_url": new_item.image_url
                    }
                    new_items_found.append(item_dict)
                    logger.info(f"[Yemen] ✓ SAVED to DB (ID: {new_item.id}): {video['title'][:50]}... from {video['source']}")
                    
                    # Process event timeline only for updates (not first run)
                    if not first_run:
                        await process_event_timeline(db, new_item.id, new_item.title, new_item.summary or '', 'yemen')
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

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_youtube_feeds())
    asyncio.create_task(fetch_yemen_youtube_feeds())
    asyncio.create_task(fetch_newspaper_feeds())

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
                else:  # newspaper
                    news_item = db.query(NewspaperNewsItem).filter(NewspaperNewsItem.id == rid).first()
                
                if news_item:
                    related_news.append({
                        "id": news_item.id,
                        "title": news_item.title,
                        "link": news_item.link,
                        "summary": news_item.summary,
                        "published": str(news_item.published),
                        "source": news_item.source,
                        "image_url": news_item.image_url,
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

@app.get("/api/debug")
async def debug_info():
    """Debug endpoint to check database status"""
    db = SessionLocal()
    try:
        world_news_count = db.query(NewsItem).count()
        yemen_news_count = db.query(YemenNewsItem).count()
        newspaper_news_count = db.query(NewspaperNewsItem).count()
        world_channels_count = db.query(ChannelLastVideo).count()
        yemen_channels_count = db.query(YemenChannelLastVideo).count()
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
                "world_channels_tracked": world_channels_count,
                "yemen_channels_tracked": yemen_channels_count,
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
        db.query(ChannelLastVideo).delete()
        db.query(YemenChannelLastVideo).delete()
        db.query(NewspaperLastArticle).delete()
        db.query(EventThread).delete()
        db.commit()
        logger.info("Manual database clear performed. All news and tracking data deleted.")
        return {"message": "All news and tracking data have been cleared successfully."}
    except Exception as e:
        db.rollback()
        logger.error(f"Error clearing database: {e}")
        return {"error": str(e)}, 500
    finally:
        db.close()

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
