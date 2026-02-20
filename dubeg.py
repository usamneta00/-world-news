import requests
import sys
import json

sys.stdout.reconfigure(encoding='utf-8')

API_URL = "https://world-news-production.up.railway.app"

def test_cluster_match(title):
    url = f"{API_URL}/api/clusters/test-match"
    params = {'title': title}

    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()

        print(f"\n{'='*60}")
        print(f"البحث عن: {title}")
        print(f"{'='*60}")

        if 'error' in data:
            print(f"خطأ: {data['error']}")
            return

        if 'message' in data and data.get('clusters_count', 0) == 0:
            print(f"تحذير: {data['message']}")
            return

        print(f"الموضوع المكتشف: {data.get('detected_topic', '?')}")
        print(f"عدد المجموعات: {data.get('clusters_count', 0)}")
        print(f"عتبة التطابق: {data.get('threshold', '?')}")

        matches = data.get('top_matches', [])
        if not matches:
            print("\nلا توجد نتائج")
            print(f"الرد الكامل: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return

        print(f"\nأقرب 10 مجموعات:")
        print(f"{'-'*60}")
        for i, m in enumerate(matches, 1):
            sim = m.get('similarity', 0)
            match_str = "سيتطابق" if m.get('would_match') else "لن يتطابق"
            print(f"{i}. [{sim:.4f}] ({match_str}) {m.get('cluster_title', '?')}")
            print(f"   ID: {m.get('cluster_id')} | أعضاء: {m.get('member_count', 0)} | حدث: {'نعم' if m.get('is_event') else 'موضوع'}")

    except Exception as e:
        print(f"خطأ: {e}")
        if 'response' in locals():
            print(f"الرد الخام: {response.text[:500]}")


def check_clusters_status():
    try:
        r = requests.get(f"{API_URL}/api/news/clusters", timeout=30)
        data = r.json()
        clusters = data.get('clusters', [])
        print(f"\n{'='*60}")
        print(f"حالة المجموعات الحالية")
        print(f"{'='*60}")
        print(f"عدد المجموعات: {data.get('total_clusters', 0)}")
        print(f"عدد الأخبار: {data.get('total_news', 0)}")
        if clusters:
            print(f"\nأكبر 5 مجموعات:")
            for i, c in enumerate(clusters[:5], 1):
                print(f"  {i}. [{c.get('news_count', 0)} أخبار] {c.get('title', '?')[:80]}")
    except Exception as e:
        print(f"خطأ: {e}")


def rebuild_clusters():
    print(f"\n{'='*60}")
    print(f"إعادة بناء المجموعات بالـ centroid embeddings...")
    print(f"{'='*60}")
    try:
        r = requests.get(f"{API_URL}/api/news/clusters?rebuild=true", timeout=120)
        data = r.json()
        print(f"تم إعادة البناء!")
        print(f"عدد المجموعات: {data.get('total_clusters', 0)}")
        print(f"عدد الأخبار: {data.get('total_news', 0)}")
    except Exception as e:
        print(f"خطأ: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        rebuild_clusters()
    else:
        check_clusters_status()
        test_cluster_match("مانميت سينغ جونيجا يتحدث عن الذكاء الاصطناعي والروبوتات")

