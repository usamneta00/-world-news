import asyncio
import logging
from datetime import datetime
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

class ChannelLastVideo(Base):
    __tablename__ = "channel_last_video"
    id = Column(Integer, primary_key=True, index=True)
    channel_name = Column(String, unique=True)
    last_video_ids = Column(String)  # JSON array of last 10 video IDs
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

class YemenChannelLastVideo(Base):
    __tablename__ = "yemen_channel_last_video"
    id = Column(Integer, primary_key=True, index=True)
    channel_name = Column(String, unique=True)
    last_video_ids = Column(String)  # JSON array of last 10 video IDs
    last_video_published = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now)

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
                # Use conn.commit() if using SQLAlchemy 2.0+ with transaction
                try: conn.commit() 
                except: pass 
                logger.info("Successfully added video_id column")
            
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
    except Exception as e:
        logger.error(f"Migration error: {e}")

# Run migration on startup
migrate_database()

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
    """Fetch NEW videos from a YouTube channel/playlist - only videos newer than any in last_video_ids (last 10)"""
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
                                'title': title,
                                'link': url,
                                'image_url': thumbnail,
                                'source': channel_name,
                                'published': published,
                                'summary': f"فيديو جديد من {channel_name}"
                            })
                            
                            # If no last_video_ids, we're in first run - collect first 10 videos
                            if not last_video_ids_set and len(videos) >= 10:
                                logger.info(f"First run for {channel_name}, collected 10 videos")
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
                                        'title': title,
                                        'link': link,
                                        'image_url': thumbnail,
                                        'source': channel_name,
                                        'published': published,
                                        'summary': f"فيديو جديد من {channel_name}"
                                    })
                                    
                                    # If no last_video_ids, we're in first run - collect first 10 videos
                                    if not last_video_ids_set and len(videos) >= 10:
                                        break
                    except Exception as e2:
                        logger.error(f"RSS fallback also failed for {channel_name}: {e2}")
        
    except Exception as e:
        logger.error(f"Error fetching YouTube channel {channel_name}: {e}")
    
    return videos

async def fetch_all_youtube_channels(db) -> List[dict]:
    """Fetch NEW videos from all YouTube channels/playlists in parallel, sorted from oldest to newest"""
    
    # Get last 10 video IDs for each channel
    channel_last_videos = {}
    for channel in YOUTUBE_CHANNELS:
        last_video_record = db.query(ChannelLastVideo).filter(ChannelLastVideo.channel_name == channel['name']).first()
        if last_video_record and last_video_record.last_video_ids:
            try:
                # Parse JSON array of last 10 video IDs
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
    
    # Get last 10 video IDs for each channel
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
            
            # Group videos by channel to track last 10 videos per channel
            videos_by_channel = {}
            for video in videos:
                channel_name = video['source']
                if channel_name not in videos_by_channel:
                    videos_by_channel[channel_name] = []
                videos_by_channel[channel_name].append(video)
            
            # Add all new videos to database
            for video in videos:
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
                logger.info(f"Added NEW video: {video['title']} from {video['source']} (published: {video['published']})")
            
            # Update last 10 videos for each channel
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
                
                # Combine: new videos + existing videos, keep only first 10
                combined_ids = new_video_ids + existing_ids
                # Remove duplicates while preserving order
                seen = set()
                unique_ids = []
                for vid_id in combined_ids:
                    if vid_id not in seen:
                        seen.add(vid_id)
                        unique_ids.append(vid_id)
                
                # Keep only last 10
                final_ids = unique_ids[:10]
                
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
        
        # Enforce 30 items limit - keep the 30 MOST RECENT videos
        total_count = db.query(NewsItem).count()
        if total_count > 30:
            # Get the IDs of the 30 newest items by published date (desc = newest first)
            latest_items = db.query(NewsItem.id).order_by(desc(NewsItem.published)).limit(30).all()
            ids_to_keep = [i[0] for i in latest_items]
            
            # Delete anything not in that list
            db.query(NewsItem).filter(NewsItem.id.not_in(ids_to_keep)).delete(synchronize_session=False)
            db.commit()
            logger.info(f"Cleanup: Kept 30 latest videos, removed {total_count - 30} older ones")
        
        # Broadcast new items (always broadcast if there are new items)
        if new_items_found:
            logger.info(f"Broadcasting {len(new_items_found)} new videos")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_news", "data": item}))
        
        db.close()
        first_run = False
        
        # Check every 3 minutes as requested
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
            
            # Group videos by channel to track last 10 videos per channel
            videos_by_channel = {}
            for video in videos:
                channel_name = video['source']
                if channel_name not in videos_by_channel:
                    videos_by_channel[channel_name] = []
                videos_by_channel[channel_name].append(video)
            
            # Add all new videos to database
            for video in videos:
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
                logger.info(f"[Yemen] Added NEW video: {video['title'][:50]}... from {video['source']}")
            
            # Update last 10 videos for each channel (track ALL fetched videos, not just Yemen-related)
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
                
                final_ids = unique_ids[:10]
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
        
        # Enforce 30 items limit for Yemen news
        total_count = db.query(YemenNewsItem).count()
        if total_count > 30:
            # Get the IDs of the 30 newest items by published date (desc = newest first)
            latest_items = db.query(YemenNewsItem.id).order_by(desc(YemenNewsItem.published)).limit(30).all()
            ids_to_keep = [i[0] for i in latest_items]
            db.query(YemenNewsItem).filter(YemenNewsItem.id.not_in(ids_to_keep)).delete(synchronize_session=False)
            db.commit()
            logger.info(f"[Yemen] Cleanup: Kept 30 latest videos, removed {total_count - 30} older ones")
        
        # Broadcast new Yemen items
        if new_items_found:
            logger.info(f"[Yemen] Broadcasting {len(new_items_found)} new Yemen videos")
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_yemen_news", "data": item}))
        
        db.close()
        first_run = False
        
        # Check every 3 minutes
        logger.info("[Yemen] Waiting 3 minutes before next fetch...")
        await asyncio.sleep(180)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_youtube_feeds())
    asyncio.create_task(fetch_yemen_youtube_feeds())

@app.get("/api/news")
async def get_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    # Order by published date from NEWEST to OLDEST (newest first on page)
    news = db.query(NewsItem).order_by(desc(NewsItem.published)).offset(skip).limit(limit).all()
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
    # Order by published date from NEWEST to OLDEST (newest first on page)
    news = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.published)).offset(skip).limit(limit).all()
    total = db.query(YemenNewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.get("/api/debug")
async def debug_info():
    """Debug endpoint to check database status"""
    db = SessionLocal()
    try:
        world_news_count = db.query(NewsItem).count()
        yemen_news_count = db.query(YemenNewsItem).count()
        world_channels_count = db.query(ChannelLastVideo).count()
        yemen_channels_count = db.query(YemenChannelLastVideo).count()
        
        # Get latest news items
        latest_world = db.query(NewsItem).order_by(desc(NewsItem.published)).limit(3).all()
        latest_yemen = db.query(YemenNewsItem).order_by(desc(YemenNewsItem.published)).limit(3).all()
        
        return {
            "database_path": DB_PATH,
            "data_dir": DATA_DIR,
            "database_exists": os.path.exists(DB_PATH),
            "database_size_kb": round(os.path.getsize(DB_PATH) / 1024, 2) if os.path.exists(DB_PATH) else 0,
            "counts": {
                "world_news": world_news_count,
                "yemen_news": yemen_news_count,
                "world_channels_tracked": world_channels_count,
                "yemen_channels_tracked": yemen_channels_count
            },
            "latest_world_news": [{"title": n.title[:50], "published": str(n.published), "source": n.source} for n in latest_world],
            "latest_yemen_news": [{"title": n.title[:50], "published": str(n.published), "source": n.source} for n in latest_yemen],
            "active_websocket_connections": len(manager.active_connections)
        }
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
