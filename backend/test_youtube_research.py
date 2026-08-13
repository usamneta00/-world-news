import asyncio
import unittest
from datetime import datetime, timezone

from youtube_research import _extract_count, _extract_date_policy, research_youtube


class YouTubeResearchTests(unittest.TestCase):
    def test_extracts_user_count_and_date_expansion(self):
        self.assertEqual(_extract_count("أريد من 6 إلى 9 فيديوهات"), {"min": 6, "max": 9})
        self.assertEqual([p["days"] for p in _extract_date_policy("آخر أسبوع ثم شهر")], [7, 30])

    def test_on_demand_pipeline_deduplicates_filters_and_verifies(self):
        today = datetime.now(timezone.utc).strftime("%Y%m%d")

        def search(query, limit):
            return [
                {"video_id": "video000001", "title": "الذكاء الاصطناعي الوكيل تحليل معمق", "channel": "قناة ألف", "url": "x"},
                {"video_id": "video000001", "title": "الذكاء الاصطناعي الوكيل تحليل معمق", "channel": "قناة ألف", "url": "x"},
                {"video_id": "video000002", "title": "الذكاء الاصطناعي الوكيل مقابلة خبير", "channel": "قناة باء", "url": "x"},
                {"video_id": "video000003", "title": "موضوع غير مرتبط", "channel": "قناة جيم", "url": "x"},
            ]

        def metadata(video_id):
            if video_id == "video000003":
                return None
            title = "الذكاء الاصطناعي الوكيل تحليل معمق" if video_id.endswith("1") else "الذكاء الاصطناعي الوكيل مقابلة خبير"
            return {
                "video_id": video_id, "title": title, "channel": "قناة ألف" if video_id.endswith("1") else "قناة باء",
                "channel_id": "channel", "uploader": "uploader", "upload_date": today,
                "timestamp": datetime.now(timezone.utc).timestamp(), "duration": 1200, "description": title + " شرح وأدلة",
                "view_count": 10000, "live_status": "not_live", "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        report = asyncio.run(research_youtube(
            "@Youtube أفضل تحليلات الذكاء الاصطناعي الوكيل، أريد فيديوهين عربيين من آخر أسبوع",
            api_key="", search_fn=search, metadata_fn=metadata,
        ))
        self.assertGreater(report["stats"]["queries"], 1)
        self.assertEqual(report["stats"]["selected"], 2)
        self.assertEqual({v["video_id"] for v in report["videos"]}, {"video000001", "video000002"})
        self.assertTrue(all(v["webpage_url"].startswith("https://youtube.com/") for v in report["videos"]))


if __name__ == "__main__":
    unittest.main()

