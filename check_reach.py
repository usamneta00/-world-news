
import requests
import hashlib
from urllib.parse import urljoin, urlparse

def generate_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]

sources = [
    ("https://www.washingtonpost.com/world/middle-east/", "Washington Post"),
    ("https://www.theguardian.com/world/middleeast", "The Guardian"),
    ("https://foreignpolicy.com/tag/middle-east-and-north-africa/", "Foreign Policy"),
    ("https://www.reuters.com/world/middle-east/", "Reuters"),
    ("https://www.ynetnews.com/category/3083", "Ynet News")
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

for url, name in sources:
    print(f"\nChecking {name}...")
    try:
        r = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {r.status_code}")
        print(f"Length: {len(r.content)}")
    except Exception as e:
        print(f"Error: {e}")
