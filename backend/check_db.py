import sqlite3
import os

db_path = 'e:/yemen/‏‏world-news/world_news.db'
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    # Try current directory
    db_path = 'world_news.db'

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    tables = [
        "news", "yemen_news", "newspaper_news", "trending_topics", 
        "event_threads", "news_clusters", "news_cluster_members"
    ]
    
    for table in tables:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"Table {table}: {count} rows")
            if count > 0 and table == "trending_topics":
                cursor.execute(f"SELECT * FROM {table} LIMIT 5")
                rows = cursor.fetchall()
                for row in rows:
                    print(f"  Row: {row}")
        except Exception as e:
            print(f"Error reading table {table}: {e}")
            
    conn.close()
else:
    print("Database file not found.")
