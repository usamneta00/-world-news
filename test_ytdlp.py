#!/usr/bin/env python3
"""
مثال بسيط لاستخدام yt-dlp لجلب آخر 10 فيديوهات من قناة يوتيوب
"""

import yt_dlp
from datetime import datetime

def fetch_latest_videos(channel_url, max_videos=10):
    """
    جلب آخر فيديوهات من قناة يوتيوب
    
    Args:
        channel_url: رابط القناة (مثال: https://www.youtube.com/@Reuters/videos)
        max_videos: عدد الفيديوهات المطلوبة (افتراضي: 10)
    """
    
    print(f"🔍 جاري جلب آخر {max_videos} فيديو من: {channel_url}\n")
    
    # إعدادات yt-dlp
    ydl_opts = {
        'quiet': True,              # عدم طباعة تفاصيل كثيرة
        'no_warnings': True,        # إخفاء التحذيرات
        'extract_flat': True,       # جلب المعلومات فقط (بدون تحميل الفيديو)
        'playlistend': 50,          # فحص أول 50 فيديو من القناة
        'ignoreerrors': True,       # تجاهل الأخطاء والاستمرار
    }
    
    videos = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # استخراج معلومات القناة
            info = ydl.extract_info(channel_url, download=False)
            
            if info and 'entries' in info:
                entries_list = list(info['entries']) if info['entries'] else []
                
                print(f"✅ تم العثور على {len(entries_list)} فيديو في القناة\n")
                
                # جلب أول max_videos فيديو
                for idx, entry in enumerate(entries_list[:max_videos], 1):
                    if entry:
                        video_id = entry.get('id')
                        title = entry.get('title', 'No Title')
                        
                        # تخطي الفيديوهات المحذوفة أو الخاصة
                        if not title or title in ['[Private video]', '[Deleted video]']:
                            continue
                        
                        # الحصول على تاريخ النشر
                        upload_date = entry.get('upload_date')
                        if upload_date:
                            try:
                                published = datetime.strptime(upload_date, '%Y%m%d')
                                published_str = published.strftime('%Y-%m-%d')
                            except:
                                published_str = 'Unknown'
                        else:
                            published_str = 'Unknown'
                        
                        # رابط الفيديو
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        # الصورة المصغرة
                        thumbnail = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                        
                        video_info = {
                            'number': idx,
                            'video_id': video_id,
                            'title': title,
                            'url': video_url,
                            'published': published_str,
                            'thumbnail': thumbnail
                        }
                        
                        videos.append(video_info)
                        
                        # طباعة معلومات الفيديو
                        print(f"📹 فيديو #{idx}")
                        print(f"   العنوان: {title}")
                        print(f"   الرابط: {video_url}")
                        print(f"   تاريخ النشر: {published_str}")
                        print(f"   الصورة: {thumbnail}")
                        print()
                
    except Exception as e:
        print(f"❌ خطأ: {e}")
    
    return videos


if __name__ == "__main__":
    # أمثلة على قنوات مختلفة
    channels = [
        "https://www.youtube.com/@Reuters/videos",
        "https://www.youtube.com/@aljazeeraenglish/videos",
        "https://www.youtube.com/@BBCNews/videos",
    ]
    
    print("=" * 80)
    print("مثال على استخدام yt-dlp لجلب آخر 10 فيديوهات من قناة يوتيوب")
    print("=" * 80)
    print()
    
    # اختر قناة للاختبار (افتراضياً Reuters)
    test_channel = channels[0]
    
    # جلب آخر 10 فيديوهات
    videos = fetch_latest_videos(test_channel, max_videos=10)
    
    print("=" * 80)
    print(f"✅ تم جلب {len(videos)} فيديو بنجاح!")
    print("=" * 80)
