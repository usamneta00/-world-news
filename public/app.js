const API_BASE = '/api';
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

let state = {
    activeTab: 'world',
    worldNews: [],
    yemenNews: [],
    worldPending: [],
    yemenPending: [],
    worldPage: 1,
    yemenPage: 1,
    worldTotal: 0,
    yemenTotal: 0,
    loading: true,
    connected: false
};

// DOM elements
const elements = {
    dateDisplay: document.getElementById('date-display'),
    liveStatus: document.getElementById('live-status'),
    breakingTicker: document.getElementById('breaking-ticker'),
    tickerText: document.getElementById('ticker-text'),
    newNewsBanner: document.getElementById('new-news-banner'),
    pendingCount: document.getElementById('pending-count'),
    loadingState: document.getElementById('loading-state'),
    newsLayout: document.getElementById('news-layout'),
    featuredSection: document.getElementById('featured-section'),
    secondaryGrid: document.getElementById('secondary-grid'),
    newsFeed: document.getElementById('news-feed'),
    trendingList: document.getElementById('trending-list'),
    emptyState: document.getElementById('empty-state'),
    pagination: document.getElementById('pagination'),
    prevPage: document.getElementById('prev-page'),
    nextPage: document.getElementById('next-page'),
    pageNum: document.getElementById('page-num'),
    footerYear: document.getElementById('footer-year'),
    tabWorld: document.getElementById('tab-world'),
    tabYemen: document.getElementById('tab-yemen'),
    tabWorldMobile: document.getElementById('tab-world-mobile'),
    tabYemenMobile: document.getElementById('tab-yemen-mobile')
};

// Initialization
function init() {
    // Set date
    const today = new Date().toLocaleDateString('ar-EG', {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
    elements.dateDisplay.textContent = today;
    elements.footerYear.textContent = new Date().getFullYear();

    // Fetch initial news
    fetchNews(state.worldPage);

    // Setup WebSockets
    setupWebSocket();

    // Event listeners
    elements.prevPage.addEventListener('click', () => {
        if (state.activeTab === 'world' && state.worldPage > 1 && !state.loading) {
            state.worldPage--;
            fetchNews(state.worldPage);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else if (state.activeTab === 'yemen' && state.yemenPage > 1 && !state.loading) {
            state.yemenPage--;
            fetchYemenNews(state.yemenPage);
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    elements.nextPage.addEventListener('click', () => {
        if (state.activeTab === 'world') {
            const maxPages = Math.ceil(state.worldTotal / 20);
            if (state.worldPage < maxPages && !state.loading) {
                state.worldPage++;
                fetchNews(state.worldPage);
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        } else {
            const maxPages = Math.ceil(state.yemenTotal / 20);
            if (state.yemenPage < maxPages && !state.loading) {
                state.yemenPage++;
                fetchYemenNews(state.yemenPage);
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
    });

    elements.newNewsBanner.addEventListener('click', showPendingNews);
}

function switchTab(tab) {
    state.activeTab = tab;

    // Update desktop tabs
    if (tab === 'world') {
        elements.tabWorld.className = 'px-5 py-2 rounded-full text-xs font-bold transition-all text-white bg-white/10 shadow-sm';
        elements.tabYemen.className = 'px-5 py-2 rounded-full text-xs font-bold transition-all text-zinc-400 hover:text-white';
        elements.tabWorldMobile.className = 'flex-1 px-4 py-2 rounded-lg text-xs font-bold transition-all bg-brand-500 text-white';
        elements.tabYemenMobile.className = 'flex-1 px-4 py-2 rounded-lg text-xs font-bold transition-all text-zinc-400 bg-zinc-900';

        if (state.worldNews.length === 0) {
            fetchNews(state.worldPage);
        } else {
            renderNews();
        }
    } else {
        elements.tabYemen.className = 'px-5 py-2 rounded-full text-xs font-bold transition-all text-white bg-white/10 shadow-sm';
        elements.tabWorld.className = 'px-5 py-2 rounded-full text-xs font-bold transition-all text-zinc-400 hover:text-white';
        elements.tabYemenMobile.className = 'flex-1 px-4 py-2 rounded-lg text-xs font-bold transition-all bg-brand-500 text-white';
        elements.tabWorldMobile.className = 'flex-1 px-4 py-2 rounded-lg text-xs font-bold transition-all text-zinc-400 bg-zinc-900';

        if (state.yemenNews.length === 0) {
            fetchYemenNews(state.yemenPage);
        } else {
            renderNews();
        }
    }

    updateUI();
    lucide.createIcons();
}

function timeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    let interval = seconds / 31536000;
    if (interval > 1) return `منذ ${Math.floor(interval)} سنة`;
    interval = seconds / 2592000;
    if (interval > 1) return `منذ ${Math.floor(interval)} شهر`;
    interval = seconds / 86400;
    if (interval > 1) return `منذ ${Math.floor(interval)} يوم`;
    interval = seconds / 3600;
    if (interval > 1) return `منذ ${Math.floor(interval)} ساعة`;
    interval = seconds / 60;
    if (interval > 1) return `منذ ${Math.floor(interval)} دقيقة`;
    return 'الآن';
}

async function fetchNews(p) {
    state.loading = true;
    updateUI();
    try {
        const resp = await fetch(`${API_BASE}/news?page=${p}&limit=20`);
        const data = await resp.json();
        state.worldNews = data.items;
        state.worldTotal = data.total;
        state.worldPage = data.page;

        if (state.activeTab === 'world') {
            renderNews();
        }
    } catch (err) {
        console.error("Failed to fetch news", err);
    } finally {
        state.loading = false;
        updateUI();
    }
}

async function fetchYemenNews(p) {
    state.loading = true;
    updateUI();
    try {
        const resp = await fetch(`${API_BASE}/yemen-news?page=${p}&limit=20`);
        const data = await resp.json();
        state.yemenNews = data.items;
        state.yemenTotal = data.total;
        state.yemenPage = data.page;

        if (state.activeTab === 'yemen') {
            renderNews();
        }
    } catch (err) {
        console.error("Failed to fetch Yemen news", err);
    } finally {
        state.loading = false;
        updateUI();
    }
}

function updateUI() {
    const currentNews = state.activeTab === 'world' ? state.worldNews : state.yemenNews;
    const currentPage = state.activeTab === 'world' ? state.worldPage : state.yemenPage;
    const currentTotal = state.activeTab === 'world' ? state.worldTotal : state.yemenTotal;
    const currentPending = state.activeTab === 'world' ? state.worldPending : state.yemenPending;

    elements.loadingState.style.display = state.loading && currentNews.length === 0 ? 'block' : 'none';
    elements.newsLayout.style.display = currentNews.length > 0 ? 'block' : 'none';
    elements.emptyState.style.display = !state.loading && currentNews.length === 0 ? 'block' : 'none';
    elements.pagination.style.display = currentTotal > 20 ? 'flex' : 'none';
    elements.liveStatus.style.display = state.connected ? 'flex' : 'none';

    elements.pageNum.textContent = currentPage;
    elements.prevPage.disabled = currentPage === 1 || state.loading;
    const maxPages = Math.ceil(currentTotal / 20);
    elements.nextPage.disabled = currentPage >= maxPages || state.loading;

    if (currentPending.length > 0 && currentPage === 1) {
        elements.newNewsBanner.style.display = 'block';
        elements.pendingCount.textContent = currentPending.length;
    } else {
        elements.newNewsBanner.style.display = 'none';
    }
}

function renderNews() {
    const news = state.activeTab === 'world' ? state.worldNews : state.yemenNews;

    if (news.length === 0) {
        elements.emptyState.style.display = 'block';
        elements.featuredSection.innerHTML = '';
        elements.secondaryGrid.innerHTML = '';
        elements.newsFeed.innerHTML = '';
        elements.breakingTicker.style.display = 'none';
        return;
    }

    elements.emptyState.style.display = 'none';

    // Breaking Ticker
    elements.breakingTicker.style.display = 'flex';
    elements.tickerText.textContent = news[0].title;

    const currentPage = state.activeTab === 'world' ? state.worldPage : state.yemenPage;
    const featured = currentPage === 1 ? news[0] : null;
    const secondary = currentPage === 1 ? news.slice(1, 4) : [];
    const others = currentPage === 1 ? news.slice(4) : news;

    // Featured
    if (featured) {
        elements.featuredSection.style.display = 'block';
        elements.featuredSection.innerHTML = `
            <a href="${featured.link}" target="_blank" rel="noopener noreferrer" class="block group">
                <div class="relative aspect-[21/9] rounded-[40px] overflow-hidden bg-zinc-900 border border-white/5">
                    ${featured.image_url ? `<img src="${featured.image_url}" alt="${featured.title}" class="w-full h-full object-cover opacity-60 group-hover:opacity-100 group-hover:scale-105 transition-all duration-700">` : '<div class="w-full h-full bg-zinc-800"></div>'}
                    <div class="absolute inset-0 bg-gradient-to-t from-black via-black/40 to-transparent"></div>
                    <div class="absolute bottom-0 right-0 left-0 p-8 md:p-12 space-y-4">
                        <span class="px-4 py-1.5 bg-brand-500 text-white text-[10px] font-bold uppercase tracking-widest rounded-full">${featured.source}</span>
                        <h2 class="text-3xl md:text-5xl font-black text-white leading-tight max-w-4xl font-serif">${featured.title}</h2>
                        <div class="flex items-center gap-4 text-zinc-400 text-xs font-bold">
                            <span class="flex items-center gap-2"><i data-lucide="clock" class="w-4 h-4 text-brand-500"></i> ${timeAgo(featured.published)}</span>
                        </div>
                    </div>
                </div>
            </a>
        `;
    } else {
        elements.featuredSection.style.display = 'none';
    }

    // Secondary
    if (secondary.length > 0) {
        elements.secondaryGrid.style.display = currentPage === 1 ? 'grid' : 'none';
        elements.secondaryGrid.innerHTML = secondary.map(item => `
            <a href="${item.link}" target="_blank" rel="noopener noreferrer" class="glass-panel rounded-[32px] overflow-hidden group hover:border-brand-500/50 transition-all duration-500">
                <div class="aspect-video relative overflow-hidden">
                    ${item.image_url ? `<img src="${item.image_url}" alt="${item.title}" class="w-full h-full object-cover opacity-80 group-hover:opacity-100 group-hover:scale-110 transition-all duration-700">` : '<div class="w-full h-full bg-zinc-800"></div>'}
                    <div class="absolute top-4 right-4">
                        <span class="px-3 py-1 bg-black/60 backdrop-blur-md text-[9px] font-black text-white border border-white/10 rounded-full uppercase tracking-tighter">${item.source}</span>
                    </div>
                </div>
                <div class="p-6 space-y-3">
                    <h3 class="text-lg font-bold text-white leading-snug group-hover:text-brand-500 transition-colors line-clamp-2">${item.title}</h3>
                    <span class="text-[10px] font-bold text-zinc-500 font-mono">${timeAgo(item.published)}</span>
                </div>
            </a>
        `).join('');
    } else {
        elements.secondaryGrid.style.display = 'none';
    }

    // Main Feed
    elements.newsFeed.innerHTML = others.map(item => `
        <div class="glass-panel p-6 rounded-[32px] group hover:border-white/20 transition-all duration-300">
            <div class="flex flex-col md:flex-row gap-6">
                <div class="flex-1 space-y-4">
                    <div class="flex items-center gap-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-brand-500"></span>
                        <span class="text-[10px] font-black text-brand-500 uppercase tracking-widest">${item.source}</span>
                        <span class="text-zinc-600 text-xs">•</span>
                        <span class="text-[10px] font-bold text-zinc-500 font-mono">${timeAgo(item.published)}</span>
                    </div>
                    <a href="${item.link}" target="_blank" rel="noopener noreferrer" class="block">
                        <h3 class="text-xl font-bold text-white group-hover:text-brand-500 transition-colors leading-normal">${item.title}</h3>
                    </a>
                    <p class="text-zinc-400 text-sm leading-relaxed line-clamp-2">${item.summary}</p>
                    <div class="pt-2">
                        <a href="${item.link}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-2 text-white text-[10px] font-black uppercase tracking-widest hover:gap-4 transition-all">
                            اقرأ المزيد <i data-lucide="arrow-left" class="w-3 h-3 text-brand-500"></i>
                        </a>
                    </div>
                </div>
                ${item.image_url ? `
                    <div class="w-full md:w-56 h-40 rounded-2xl overflow-hidden border border-white/5 flex-shrink-0">
                        <img src="${item.image_url}" alt="${item.title}" class="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700">
                    </div>
                ` : ''}
            </div>
        </div>
    `).join('');

    // Trending
    elements.trendingList.innerHTML = news.slice(0, 6).map((item, idx) => `
        <a href="${item.link}" target="_blank" rel="noopener noreferrer" class="flex gap-4 group">
            <span class="text-3xl font-black text-zinc-800 font-serif group-hover:text-brand-500 transition-colors">${idx + 1}</span>
            <div class="space-y-1">
                <p class="text-sm font-bold text-zinc-300 group-hover:text-white transition-colors leading-snug line-clamp-2">${item.title}</p>
                <span class="text-[9px] font-bold text-zinc-600 uppercase">${item.source}</span>
            </div>
        </a>
    `).join('');

    lucide.createIcons();
}

function setupWebSocket() {
    let ws;
    const connect = () => {
        ws = new WebSocket(WS_URL);
        ws.onopen = () => {
            state.connected = true;
            updateUI();
        };
        ws.onmessage = (event) => {
            const message = JSON.parse(event.data);
            if (message.type === 'new_news') {
                const newItem = message.data;
                const allCurrentLinks = new Set([...state.worldNews.map(n => n.link), ...state.worldPending.map(n => n.link)]);
                if (!allCurrentLinks.has(newItem.link)) {
                    state.worldPending.unshift(newItem);
                    state.worldTotal++;
                    if (state.activeTab === 'world') updateUI();
                }
            } else if (message.type === 'new_yemen_news') {
                const newItem = message.data;
                const allCurrentLinks = new Set([...state.yemenNews.map(n => n.link), ...state.yemenPending.map(n => n.link)]);
                if (!allCurrentLinks.has(newItem.link)) {
                    state.yemenPending.unshift(newItem);
                    state.yemenTotal++;
                    if (state.activeTab === 'yemen') updateUI();
                }
            }
        };
        ws.onclose = () => {
            state.connected = false;
            updateUI();
            setTimeout(connect, 5000);
        };
    };
    connect();
}

function showPendingNews() {
    if (state.activeTab === 'world') {
        state.worldNews = [...state.worldPending, ...state.worldNews].slice(0, 20);
        state.worldPending = [];
        state.worldPage = 1;
    } else {
        state.yemenNews = [...state.yemenPending, ...state.yemenNews].slice(0, 20);
        state.yemenPending = [];
        state.yemenPage = 1;
    }
    updateUI();
    renderNews();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.addEventListener('DOMContentLoaded', init);
