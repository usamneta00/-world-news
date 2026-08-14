import asyncio
import time
import unittest
from datetime import datetime, timedelta, timezone

import youtube_research as youtube_research_module
from youtube_research import _extract_count, _extract_date_policy, research_youtube, verify_video


class YouTubeResearchTests(unittest.TestCase):
    def test_extracts_user_count_and_date_expansion(self):
        self.assertEqual(_extract_count("أريد من 6 إلى 9 فيديوهات"), {"min": 7, "max": 9})
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
            filters={"strict_filters": False, "require_transcript": False, "content_type": "any", "min_discussion_score": 0, "min_reliability": 0},
        ))
        self.assertGreater(report["stats"]["queries"], 1)
        self.assertEqual(report["stats"]["selected"], 2)
        self.assertEqual({v["video_id"] for v in report["videos"]}, {"video000001", "video000002"})
        self.assertTrue(all(v["webpage_url"].startswith("https://youtube.com/") for v in report["videos"]))

    def test_returns_at_least_seven_by_relaxing_soft_constraints(self):
        now = datetime.now(timezone.utc)

        def search(query, limit):
            return [
                {"video_id": f"fillvid{i:05d}", "title": f"إيران والولايات المتحدة تحليل الصراع محورتحليلي{i}", "channel": f"قناة {i}", "url": "x"}
                for i in range(16)
            ]

        def metadata(video_id):
            index = int(video_id[-5:])
            is_strict = index == 0
            published = now if is_strict else now.replace(year=max(2000, now.year - 2))
            return {
                "video_id": video_id,
                "title": f"إيران والولايات المتحدة تحليل الصراع محورتحليلي{index}",
                "channel": f"قناة {index}", "channel_id": f"channel-{index}", "uploader": f"قناة {index}",
                "upload_date": published.strftime("%Y%m%d"), "timestamp": published.timestamp(), "duration": 900,
                "description": "تحليل سياسي وعسكري للصراع بين إيران والولايات المتحدة",
                "view_count": 10000 + index, "live_status": "not_live",
                "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        report = asyncio.run(research_youtube(
            "@Youtube إيران والولايات المتحدة وتحليل الصراع، أريد 7 فيديوهات من آخر أسبوع",
            api_key="", search_fn=search, metadata_fn=metadata,
            filters={"strict_filters": False, "require_transcript": False, "content_type": "any", "min_discussion_score": 0, "min_reliability": 0},
        ))
        self.assertEqual(report["stats"]["selected"], 7)
        self.assertEqual(report["videos"][0]["selection_tier"], "strict_match")
        self.assertTrue(any(v["selection_tier"] == "expanded_date" for v in report["videos"]))
        self.assertTrue(report["warnings"])

        first_ids = {video["video_id"] for video in report["videos"]}
        second_report = asyncio.run(research_youtube(
            "@Youtube إيران والولايات المتحدة وتحليل الصراع، أريد 7 فيديوهات من آخر أسبوع",
            api_key="", search_fn=search, metadata_fn=metadata, exclude_video_ids=first_ids,
            filters={"strict_filters": False, "require_transcript": False, "content_type": "any", "min_discussion_score": 0, "min_reliability": 0},
        ))
        second_ids = {video["video_id"] for video in second_report["videos"]}
        self.assertEqual(second_report["stats"]["selected"], 7)
        self.assertTrue(first_ids.isdisjoint(second_ids))
        self.assertEqual(second_report["stats"]["excluded_from_previous_search"], 7)

    def test_advanced_filters_transcripts_sequence_and_timeline(self):
        today = datetime.now(timezone.utc)

        def search(query, limit):
            return [
                {
                    "video_id": f"storyvid{i:04d}",
                    "title": f"حلقة نقاشية بين محللين وخبراء عن أزمة اليمن زاويةفريدة{i} محورخاص{i}",
                    "channel": "شبكة أخبار موثوقة" if i < 8 else "قناة ترفيهية",
                    "url": "x",
                }
                for i in range(12)
            ]

        def metadata(video_id):
            index = int(video_id[-4:])
            passes = index < 8
            return {
                "video_id": video_id,
                "title": f"حلقة نقاشية بين محللين وخبراء عن أزمة اليمن زاويةفريدة{index} محورخاص{index}",
                "channel": "شبكة أخبار موثوقة" if passes else "قناة ترفيهية",
                "channel_id": f"channel-{index}", "uploader": "uploader",
                "upload_date": today.strftime("%Y%m%d"), "timestamp": today.timestamp(),
                "duration": 1200 if passes else 120, "description": "أخبار اليمن وتحليل موثق بالمصادر والبيانات",
                "view_count": 50_000 if passes else 100, "live_status": "not_live",
                "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        def transcript(url):
            video_id = url.split("=")[-1]
            return {"txt": (f"{video_id} ينضم إلينا محللون وخبراء لمناقشة أزمة اليمن مع رأي آخر ومصادر وأدلة. " * 250).strip()}

        report = asyncio.run(research_youtube(
            "@Youtube ابنِ سلسلة من 7 فيديوهات تشرح تاريخ أزمة اليمن وتطوراتها",
            api_key="", search_fn=search, metadata_fn=metadata, transcript_fetcher=transcript,
            filters={
                "min_duration_minutes": 10,
                "language": "ar",
                "country": "اليمن",
                "channel_type": "news",
                "min_views": 5000,
                "min_reliability": 5,
                "live_status": "not_live",
                "require_transcript": True,
                "content_type": "panel_discussion",
                "min_discussion_score": 6,
                "strict_filters": True,
            },
        ))

        self.assertEqual(report["stats"]["selected"], 7)
        self.assertGreaterEqual(report["stats"]["transcripts_attempted"], 7)
        self.assertGreaterEqual(report["stats"]["transcripts_available"], 7)
        self.assertTrue(all(video["selection_tier"] == "strict_match" for video in report["videos"]))
        self.assertTrue(all(video["transcript_available"] for video in report["videos"]))
        self.assertEqual([video["sequence_position"] for video in report["videos"]], list(range(1, 8)))
        self.assertTrue(all(video["ordering_reason"] for video in report["videos"]))
        self.assertTrue(all(video["strengths"] and video["weaknesses"] for video in report["videos"]))
        self.assertTrue(report["timeline"]["items"])
        self.assertTrue(all(item["video_id"] for item in report["timeline"]["items"]))

    def test_rate_limit_circuit_uses_search_metadata_and_skips_transcripts(self):
        def search(query, limit):
            return [
                {
                    "video_id": f"limited{i:04d}",
                    "title": f"تحليل أزمة الشرق الأوسط زاويةفريدة{i} محورمختلف{i}",
                    "channel": f"قناة أخبار {i}",
                    "url": "x",
                    "duration": 900,
                    "view_count": 10_000 + i,
                    "language": "ar",
                }
                for i in range(10)
            ]

        previous_limit = youtube_research_module._youtube_rate_limit_until
        youtube_research_module._youtube_rate_limit_until = time.monotonic() + 60
        try:
            report = asyncio.run(research_youtube(
                "@Youtube سلسلة من 7 فيديوهات عن أزمة الشرق الأوسط",
                api_key="", search_fn=search, metadata_fn=verify_video,
                transcript_fetcher=lambda url: {"txt": "يجب ألا يُستدعى أثناء الحظر"},
                filters={"strict_filters": False, "require_transcript": True, "content_type": "any", "min_discussion_score": 0},
            ))
        finally:
            youtube_research_module._youtube_rate_limit_until = previous_limit

        self.assertEqual(report["stats"]["selected"], 7)
        self.assertGreaterEqual(report["stats"]["limited_metadata_fallbacks"], 7)
        self.assertEqual(report["stats"]["transcripts_attempted"], 0)
        self.assertGreaterEqual(report["stats"]["transcripts_skipped_rate_limit"], 7)
        self.assertTrue(all(video["metadata_limited"] for video in report["videos"]))

    def test_strict_date_never_backfills_with_old_or_unverified_videos(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=400)

        def search(query, limit):
            return [
                {
                    "video_id": f"datedpanel{i:02d}",
                    "title": f"حلقة نقاشية بين محللين وخبراء حول الحدث زاوية{i} محور{i}",
                    "channel": "شبكة أخبار رسمية",
                    "url": "x",
                }
                for i in range(10)
            ]

        def metadata(video_id):
            index = int(video_id[-2:])
            published = now if index < 3 else old
            return {
                "video_id": video_id, "title": f"حلقة نقاشية بين محللين وخبراء حول الحدث زاوية{index} محور{index}",
                "channel": "شبكة أخبار رسمية", "channel_id": f"official-{index}", "uploader": "شبكة أخبار رسمية",
                "upload_date": published.strftime("%Y%m%d"), "timestamp": published.timestamp(), "duration": 1800,
                "description": "نقاش بين عدة أطراف ومحللين وخبراء مع رأي مقابل", "view_count": 100_000,
                "live_status": "not_live", "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        report = asyncio.run(research_youtube(
            "@Youtube أريد 7 مناقشات حديثة بين محللين حول الحدث",
            api_key="", search_fn=search, metadata_fn=metadata,
            transcript_fetcher=lambda url: {"txt": "ينضم إلينا محللون وخبراء مع رأي آخر ونقاش بين عدة أطراف. " * 200},
            filters={
                "date_from": (now - timedelta(days=7)).strftime("%Y-%m-%d"),
                "date_to": now.strftime("%Y-%m-%d"),
                "channel_type": "official", "content_type": "panel_discussion",
                "min_discussion_score": 6, "min_reliability": 5,
                "require_transcript": True, "strict_filters": True,
            },
        ))

        self.assertEqual(report["stats"]["selected"], 3)
        self.assertTrue(all(video["upload_date"] == now.strftime("%Y%m%d") for video in report["videos"]))
        self.assertTrue(any("الشروط الصارمة" in warning for warning in report["warnings"]))

    def test_reuses_best_previous_results_when_youtube_has_no_new_ids(self):
        now = datetime.now(timezone.utc)

        def search(query, limit):
            return [
                {"video_id": f"repeatvid{i:02d}", "title": f"نقاش سياسي موثق زاويةفريدة{i} محورخاص{i}", "channel": f"قناة {i}", "url": "x"}
                for i in range(7)
            ]

        def metadata(video_id):
            index = int(video_id[-2:])
            return {
                "video_id": video_id, "title": f"نقاش سياسي موثق زاويةفريدة{index} محورخاص{index}",
                "channel": f"قناة {index}", "channel_id": f"channel-{index}", "uploader": f"قناة {index}",
                "upload_date": now.strftime("%Y%m%d"), "timestamp": now.timestamp(), "duration": 1200,
                "description": "نقاش سياسي موثق بالمصادر", "view_count": 20_000,
                "live_status": "not_live", "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        common = {
            "api_key": "", "search_fn": search, "metadata_fn": metadata,
            "filters": {"strict_filters": False, "require_transcript": False, "content_type": "any", "min_discussion_score": 0, "min_reliability": 0},
        }
        first = asyncio.run(research_youtube("@Youtube أريد 7 فيديوهات عن نقاش سياسي موثق", **common))
        first_ids = {video["video_id"] for video in first["videos"]}
        second = asyncio.run(research_youtube(
            "@Youtube أريد 7 فيديوهات عن نقاش سياسي موثق",
            exclude_video_ids=first_ids,
            **common,
        ))

        self.assertEqual(second["stats"]["selected"], 7)
        self.assertTrue(second["stats"]["reused_previous_results"])
        self.assertEqual(second["stats"]["new_unique"], 0)
        self.assertTrue(any("الجلسة السابقة" in warning for warning in second["warnings"]))

    def test_broad_queries_still_discover_results_when_precise_queries_are_empty(self):
        now = datetime.now(timezone.utc)

        def search(query, limit):
            if "قناة رسمية" in query or "official news channel" in query:
                return []
            return [
                {"video_id": f"broadvid{i:03d}", "title": f"حلقة نقاشية بين محللين زاوية{i} محور{i}", "channel": "شبكة أخبار", "url": "x"}
                for i in range(7)
            ]

        def metadata(video_id):
            index = int(video_id[-3:])
            return {
                "video_id": video_id, "title": f"حلقة نقاشية بين محللين زاوية{index} محور{index}",
                "channel": "شبكة أخبار", "channel_id": f"news-{index}", "uploader": "شبكة أخبار",
                "upload_date": now.strftime("%Y%m%d"), "timestamp": now.timestamp(), "duration": 1500,
                "description": "نقاش بين عدة أطراف ومحللين وخبراء", "view_count": 100_000,
                "live_status": "not_live", "original_url": f"https://youtube.com/watch?v={video_id}",
                "webpage_url": f"https://youtube.com/watch?v={video_id}", "thumbnail": "https://example.com/x.jpg",
                "language": "ar", "availability": "public",
            }

        report = asyncio.run(research_youtube(
            "@Youtube أريد 7 مناقشات بين محللين عن السياسة الدولية",
            api_key="", search_fn=search, metadata_fn=metadata,
            transcript_fetcher=lambda url: {"txt": "ينضم إلينا محللون وخبراء مع رأي آخر في هذا النقاش. " * 200},
            filters={
                "channel_type": "official", "content_type": "panel_discussion",
                "min_discussion_score": 6, "min_reliability": 5,
                "require_transcript": True, "strict_filters": True,
            },
        ))

        self.assertEqual(report["stats"]["selected"], 7)
        self.assertGreater(report["stats"]["discovered"], 0)


if __name__ == "__main__":
    unittest.main()
