import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Newspaper, Clock, ExternalLink, ChevronLeft, ChevronRight, Loader2, Wifi } from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';
import { ar } from 'date-fns/locale';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './App.css';

const API_BASE = 'http://localhost:8002/api';
const WS_URL = 'ws://localhost:8002/ws';

function App() {
  const [news, setNews] = useState([]);
  const [pendingNews, setPendingNews] = useState([]); // Buffer for new news
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);

  const fetchNews = useCallback(async (p) => {
    setLoading(true);
    try {
      const resp = await fetch(`${API_BASE}/news?page=${p}&limit=20`);
      const data = await resp.json();
      setNews(data.items);
      setTotal(data.total);
    } catch (err) {
      console.error("Failed to fetch news", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNews(page);
  }, [page, fetchNews]);

  useEffect(() => {
    let ws;
    const connectWS = () => {
      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        console.log("WS Connected");
        setConnected(true);
      };

      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'new_news') {
          const newItem = message.data;

          setPendingNews(prev => {
            // Check for duplicates in both main news and pending
            const allCurrentLinks = new Set([
              ...news.map(n => n.link),
              ...prev.map(n => n.link)
            ]);

            if (allCurrentLinks.has(newItem.link)) return prev;
            return [newItem, ...prev];
          });

          setTotal(old => old + 1);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Try to reconnect after 5 seconds
        setTimeout(connectWS, 5000);
      };
    };

    connectWS();
    return () => ws?.close();
  }, [page]);

  const showPendingNews = () => {
    setNews(prev => {
      const updated = [...pendingNews, ...prev];
      return updated.slice(0, 20); // Maintain page size
    });
    setPendingNews([]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="app-container" dir="rtl">
      <div className="main-wrapper">
        <header>
          <h1>
            <Newspaper size={40} className="text-primary" />
            الأرشيف العالمي العاجل
          </h1>
          <p className="subtitle">تغطية مباشرة لأهم الأحداث العالمية على مدار الساعة</p>
        </header>

        {connected && (
          <div className="status-bar">
            <div className="pulse-dot"></div>
            <span>مراقبة حية للحدث</span>
          </div>
        )}

        <AnimatePresence>
          {pendingNews.length > 0 && page === 1 && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: -20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: -20 }}
              className="new-news-banner"
              onClick={showPendingNews}
            >
              <Wifi size={18} />
              يوجد {pendingNews.length} أخبار جديدة - اضغط للعرض
            </motion.div>
          )}
        </AnimatePresence>

        {loading && news.length === 0 ? (
          <div className="loading-spinner">
            <Loader2 className="animate-spin" size={48} color="#e11d48" />
          </div>
        ) : (
          <div className="news-feed">
            <AnimatePresence initial={false}>
              {news.map((item) => (
                <NewsCard key={item.id} item={item} />
              ))}
            </AnimatePresence>

            {news.length === 0 && !loading && (
              <div className="empty-state">
                <h3>لا توجد أخبار حالياً</h3>
                <p>سيتم ظهور الأخبار هنا حال وصولها من المصادر</p>
              </div>
            )}
          </div>
        )}

        {totalPages > 1 && (
          <div className="pagination">
            <button
              className="page-btn"
              disabled={page === 1 || loading}
              onClick={() => {
                setPage(p => p - 1);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            >
              <ChevronRight size={20} /> السابق
            </button>
            <span className="page-info">صفحة {page} من {totalPages}</span>
            <button
              className="page-btn"
              disabled={page === totalPages || loading}
              onClick={() => {
                setPage(p => p + 1);
                window.scrollTo({ top: 0, behavior: 'smooth' });
              }}
            >
              التالي <ChevronLeft size={20} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function NewsCard({ item }) {
  const timeAgo = formatDistanceToNow(new Date(item.published), { addSuffix: true, locale: ar });

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      className={`news-card ${new Date().getTime() - new Date(item.published).getTime() < 60000 ? 'new-pulse' : ''}`}
    >
      <div className="card-header">
        <span className="source-badge">{item.source}</span>
        <span className="publish-time">
          <Clock size={14} />
          {timeAgo}
        </span>
      </div>

      <div className="card-content">
        <a href={item.link} target="_blank" rel="noopener noreferrer" className="card-link">
          {item.image_url && (
            <div className="card-image-wrapper">
              <img src={item.image_url} alt={item.title} className="card-image" loading="lazy" />
            </div>
          )}
          <h2>{item.title}</h2>
        </a>
        <div className="card-summary">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {item.summary}
          </ReactMarkdown>
        </div>
      </div>

      <div className="card-footer">
        <a href={item.link} target="_blank" rel="noopener noreferrer" className="read-more">
          مشاهدة الخبر الكامل <ExternalLink size={16} />
        </a>
      </div>
    </motion.div>
  );
}

export default App;
