
import asyncio
import feedparser
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from bs4 import BeautifulSoup
import json
import time
import re
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from openai import OpenAI
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./world_news.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
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

Base.metadata.create_all(bind=engine)

# OpenAI Client Setup
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

def get_video_id(url: str) -> str:
    """Extract YouTube video ID from a variety of URL formats."""
    url = url.strip()
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0].split("&")[0]
    if "youtube.com/watch" in url and "v=" in url:
        # e.g. https://www.youtube.com/watch?v=VIDEO_ID&...
        parts = url.split("v=")[1]
        return parts.split("&")[0]
    # Fallback: assume user pasted just the ID
    return url

async def fetch_transcript(video_id: str) -> str:
    """Fetch transcript text for a given video_id."""
    try:
        logger.info(f"بدء جلب الـ transcript للفيديو: {video_id}")
        # استخدام الأسلوب الذي يعمل في مشروع downsub-summary
        transcripts = YouTubeTranscriptApi().list(video_id)

        # نحاول اختيار العربية أو الإنجليزية إن وجدت، وإلا نأخذ أول واحد
        preferred = None
        for t in transcripts:
            lang = getattr(t, "language_code", None)
            if lang in ("ar", "ar-SA", "en", "en-US"):
                preferred = t
                break

        transcript = preferred or next(iter(transcripts))

        fetched = transcript.fetch()
        # كائنات المكتبة ترجع عادةً dict يحتوي على "text"
        raw = "\n".join(
            sn["text"] if isinstance(sn, dict) else getattr(sn, "text", "")
            for sn in fetched
        )
        text = " ".join(raw.splitlines())
        logger.info(f"[Transcript] Successfully fetched for {video_id} ({len(text)} chars)")
        return text
    except Exception as e:
        logger.warning(f"[Transcript] Not found or disabled for {video_id}: {e}")
        return ""

async def generate_facebook_content(title: str, transcript: str) -> str:
    if not transcript and not title:
        return ""
    
    try:
        prompt = f"""
أنت خبير في إدارة صفحات الفيسبوك الإخبارية. قم بتحويل المحتوى التالي (عنوان وفيديو) إلى منشور فيسبوك جذاب واحترافي. 
يجب أن يكون المنشور بتنسيق:
1. مقدمة مثيرة (Hook).
2. ملخص ذكي للمحتوى بأسلوب مشوق.
3. استخدام الرموز التعبيرية (Emojis) بشكل مناسب.
4. وسم (Hashtags) ذات صلة.

العنوان: {title}
المحتوى الأساسي: {transcript[:2000] if transcript else "استخدم العنوان فقط للتوسع في الموضوع"}

اكتب المنشور باللغة العربية بأسلوب "صحفي مثير". لا تذكر كلمة "فيديو" أو "يوتيوب".
"""
        response = client.responses.create(
            model="gpt-5.2",
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt,
                        }
                    ],
                }
            ],
        )
        return response.output_text.strip()
    except Exception as e:
        logger.error(f"Error generating FB content: {e}")
        return title

def translate_title_to_arabic(title: str) -> str:
    """
    ترجمة عنوان الفيديو من الإنجليزية إلى العربية باستخدام OpenAI.
    إذا كان العنوان بالفعل بالعربية أو قصير جدًا، نرجعه كما هو.
    """
    if not title or len(title.strip()) < 3:
        return title
    
    if len(title.strip()) < 10:
        return title
    
    try:
        model = "gpt-5.2"
        
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"قم بترجمة العنوان التالي من الإنجليزية إلى العربية، وأرجع الترجمة فقط بدون أي شرح أو نص إضافي:\n\n{title}",
                        }
                    ],
                }
            ],
        )
        
        translated = response.output_text.strip()
        if translated and len(translated) > 0:
            return translated
    except Exception as exc:
        logger.warning(f"تعذر ترجمة العنوان: {exc}")
    
    return title

async def summarize_text(text: str, locale: str = "ar", title: str | None = None) -> str:
    """Summarize a transcript using OpenAI."""
    if not text:
        return "لا يوجد نص متاح لهذا الفيديو (لم يتم العثور على Transcript أو تم تعطيله)."

    model = "gpt-5.2"

    if locale == "ar":
        system_prompt = (
            "اريد ان تدخل في الموضوع مباشرة ولا تضيف اي شي اخر\n"
            "أنت كاتب عربي يصوغ ملخصات تبدو بشرية وطبيعية.\n"
            "اكتب فقرة واحدة مترابطة تشرح الفكرة الأساسية وأهم الرسائل أو النتائج.\n"
            "استخدم الخط العريض (Bold) لتمييز الكلمات المفتاحية والمعلومات الهامة فقط، تماماً كما في منشورات الفيسبوك الاحترافية.\n"
            "يُمنع منعاً باتاً استخدام الرموز التعبيرية (Emojis) أو الأشكال أو الرموز الزخرفية في النص.\n"
            "تجنّب تمامًا العبارات التي تكشف أن النص ملخص مثل: «يتحدث الفيديو عن» أو «في هذا النص».\n"
            "اكتب المحتوى مباشرة بصيغة تقريرية واضحة ونظيفة."
        )
        user_prompt = (
            "استخرج أهم ما يفيد القارئ من النص التالي، واكتبه في فقرة عربية واحدة متصلة، "
            "مع إبراز الكلمات الهامة بخط عريض، وبدون أي رموز تعبيرية أو تعداد نقطي:\n\n"
            f"{text}"
        )
    else:
        system_prompt = (
            "Directly cover the topic without extra fluff.\n"
            "Write a natural, human-like summary in a single coherent paragraph.\n"
            "Use bold text to highlight key information and important terms.\n"
            "Strictly avoid using emojis, symbols, or decorative icons.\n"
            "Do not mention that this is a summary or transcript.\n"
            "Write clearly and professionally."
        )
        user_prompt = (
            "Extract the main points into one continuous paragraph, highlighting key terms in bold. "
            "Do not use emojis or bullet points:\n\n"
            f"{text}"
        )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": system_prompt,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_prompt,
                        }
                    ],
                },
            ],
        )
        summary = response.output_text.strip()
        
        if title and title.strip():
            translated_title = translate_title_to_arabic(title.strip())
            return f"{translated_title}\n\n{summary}"
        
        return summary
    except Exception as e:
        logger.error(f"Error in summarize_text: {e}")
        return "حدث خطأ أثناء التلخيص."

# RSS Feeds list
RSS_FEEDS = [
    "https://rss.app/feeds/_tYWt4uOevmy5W5KP.xml"
]

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
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()

def parse_date(date_string):
    try:
        # Common RSS date format
        return datetime(*(feedparser._parse_date(date_string)[:6]))
    except:
        return datetime.now()

async def fetch_rss_feeds():
    first_run = True
    while True:
        db = SessionLocal()
        new_items_found = []
        for url in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                source_name = feed.feed.get('title', 'World News')
                # Process entries in reverse (oldest to newest) so newest gets the highest ID
                for entry in reversed(feed.entries):
                    link = entry.get('link')
                    # Check if exists
                    exists = db.query(NewsItem).filter(NewsItem.link == link).first()
                    if not exists:
                        # Try to find image
                        image_url = None
                        if 'media_content' in entry:
                            image_url = entry.media_content[0].get('url')
                        elif 'links' in entry:
                            for l in entry.links:
                                if 'image' in l.get('type', ''):
                                    image_url = l.get('href')
                        
                        published = parse_date(entry.get('published', ''))
                        
                        # Check if it's a YouTube link
                        video_id = get_video_id(link)
                        
                        if video_id and not first_run:
                            logger.info(f"Processing YouTube video with AI: {video_id}")
                            transcript = await fetch_transcript(video_id)
                            # Generate FB content
                            fb_content = await generate_facebook_content(entry.get('title', ''), transcript)
                            # Generate Summary (as in downsub)
                            video_summary = await summarize_text(transcript, locale="ar", title=entry.get('title', ''))
                            # Combine them: Facebook content followed by the deep summary
                            clean_summary = f"{fb_content}\n\n---\n\n{video_summary}"
                        else:
                            if video_id and first_run:
                                logger.info(f"First run: Skipping AI for video {video_id}")
                            
                            # Clean summary from HTML for non-YT items OR for YT items on first run
                            raw_summary = entry.get('summary', '') or entry.get('title', '')
                            clean_summary = BeautifulSoup(raw_summary, "html.parser").get_text()
                        
                        new_item = NewsItem(
                            title=entry.get('title'),
                            link=link,
                            summary=clean_summary,
                            published=published,
                            source=source_name,
                            image_url=image_url
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
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
        
        # Enforce 100 items limit for World News (higher than Yemen)
        total_count = db.query(NewsItem).count()
        if total_count > 100:
            ids_to_keep = db.query(NewsItem.id).order_by(desc(NewsItem.id)).limit(100).all()
            ids_to_keep = [i[0] for i in ids_to_keep]
            db.query(NewsItem).filter(NewsItem.id.not_in(ids_to_keep)).delete(synchronize_session=False)
            db.commit()

        # Broadcast new items
        if new_items_found and not first_run:
            for item in new_items_found:
                await manager.broadcast(json.dumps({"type": "new_news", "data": item}))

        db.close()
        first_run = False
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(fetch_rss_feeds())

@app.get("/api/news")
async def get_news(page: int = 1, limit: int = 20):
    db = SessionLocal()
    skip = (page - 1) * limit
    news = db.query(NewsItem).order_by(desc(NewsItem.id)).offset(skip).limit(limit).all()
    total = db.query(NewsItem).count()
    db.close()
    return {
        "items": news,
        "total": total,
        "page": page,
        "limit": limit
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
