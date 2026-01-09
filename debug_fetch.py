
import requests
from bs4 import BeautifulSoup
import hashlib
from urllib.parse import urljoin, urlparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]

def debug_fetch(source_url, source_name):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
    }
    
    print(f"--- Fetching {source_name}: {source_url} ---")
    try:
        response = requests.get(source_url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
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
        article_links = []
        for selector in selectors:
            elements = soup.select(selector)
            for elem in elements:
                href = elem.get('href')
                if href:
                    full_url = urljoin(source_url, href)
                    parsed = urlparse(full_url)
                    if (parsed.scheme in ['http', 'https'] and 
                        not any(x in full_url.lower() for x in ['/video/', '/videos/', '/live/', '/author/', '/tag/', '/category/', '/search/', '#', 'javascript:', 'mailto:'])):
                        if full_url not in found_links:
                            found_links.add(full_url)
                            title = elem.get_text(strip=True)
                            if not title or len(title) < 10:
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
        
        print(f"Found {len(article_links)} potential articles")
        for a in article_links[:10]:
            print(f"- {a['title'][:50]}... ({a['url']})")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_fetch("https://www.washingtonpost.com/world/middle-east/", "Washington Post")
    debug_fetch("https://www.theguardian.com/world/middleeast", "The Guardian")
    debug_fetch("https://foreignpolicy.com/tag/middle-east-and-north-africa/", "Foreign Policy")
