import re
import os

filepath = r"e:\yemen\‏‏world-news\public\index.html"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace the CSS block
css_old_start = "/* ===== News Clustering Styles ===== */"
css_old_end = "</style>"

css_new = """/* ===== News Clustering Styles ===== */
        .cluster-card {
            background: rgba(255, 255, 255, 0.02);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 20px;
            padding: 24px;
            transition: all 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
            cursor: pointer;
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.1);
        }

        .dark .cluster-card {
            background: rgba(15, 15, 15, 0.6);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4);
        }

        .cluster-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 100%;
            background: radial-gradient(800px circle at var(--mouse-x, 0) var(--mouse-y, 0), rgba(255,255,255,0.06), transparent 40%);
            opacity: 0;
            transition: opacity 0.5s;
            pointer-events: none;
            z-index: 0;
        }

        .cluster-card:hover::before { opacity: 1; }

        .cluster-card:hover {
            transform: translateY(-4px) scale(1.01);
            border-color: rgba(255, 255, 255, 0.15);
            box-shadow: 0 20px 40px -10px rgba(0, 0, 0, 0.5);
        }

        .cluster-card.expanded {
            border-color: rgba(59, 130, 246, 0.5);
            background: rgba(59, 130, 246, 0.03);
            box-shadow: 0 0 40px rgba(59, 130, 246, 0.1);
        }

        .cluster-count-badge {
            display: inline-flex; align-items: center; justify-content: center;
            min-width: 42px; height: 42px;
            background: linear-gradient(135deg, rgba(255,255,255,0.1), rgba(255,255,255,0.02));
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            font-size: 18px; font-weight: 800; color: #fff;
            font-family: 'JetBrains Mono', monospace;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            position: relative; z-index: 1;
        }

        .cluster-source-tag {
            display: inline-flex; align-items: center; gap: 4px;
            padding: 4px 12px; border-radius: 20px;
            font-size: 11px; font-weight: 600;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.05);
            color: #9ca3af; transition: all 0.3s ease;
            position: relative; z-index: 1; backdrop-filter: blur(4px);
        }

        .cluster-source-tag:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: rgba(255, 255, 255, 0.2);
            color: #fff; transform: translateY(-1px);
        }

        .cluster-type-dot {
            width: 8px; height: 8px; border-radius: 50%;
            display: inline-block; box-shadow: 0 0 10px currentColor;
        }

        .cluster-type-dot.world { color: #3b82f6; background: #3b82f6; }
        .cluster-type-dot.yemen { color: #10b981; background: #10b981; }
        .cluster-type-dot.newspaper { color: #f59e0b; background: #f59e0b; }

        .cluster-news-list {
            max-height: 0; overflow: hidden;
            transition: max-height 0.6s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative; z-index: 1;
        }

        .cluster-news-list.open { max-height: 2000px; }

        .cluster-news-item {
            display: flex; gap: 16px; padding: 16px; margin-bottom: 8px;
            border-radius: 12px; background: rgba(255, 255, 255, 0.02);
            border: 1px solid transparent; transition: all 0.3s ease;
            text-decoration: none; color: inherit;
        }

        .cluster-news-item:hover {
            background: rgba(255, 255, 255, 0.06);
            border-color: rgba(255, 255, 255, 0.1);
            transform: translateX(-4px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .cluster-news-thumb {
            width: 90px; height: 64px; border-radius: 8px;
            object-fit: cover; flex-shrink: 0; opacity: 0.9;
            transition: all 0.3s ease; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
        }

        .cluster-news-item:hover .cluster-news-thumb { opacity: 1; transform: scale(1.05); }

        .cluster-intensity-bar {
            width: 6px; border-radius: 6px; position: absolute;
            top: 16px; bottom: 16px; right: 0; opacity: 0.8;
            transition: opacity 0.3s ease, width 0.3s ease;
        }
        
        .cluster-card:hover .cluster-intensity-bar { opacity: 1; width: 8px; }

        .cluster-intensity-bar.conflict { background: linear-gradient(180deg, #ef4444, #991b1b); box-shadow: -2px 0 12px rgba(239, 68, 68, 0.5); }
        .cluster-intensity-bar.crisis { background: linear-gradient(180deg, #f59e0b, #b45309); box-shadow: -2px 0 12px rgba(245, 158, 11, 0.5); }
        .cluster-intensity-bar.important { background: linear-gradient(180deg, #3b82f6, #1d4ed8); box-shadow: -2px 0 12px rgba(59, 130, 246, 0.5); }
        .cluster-intensity-bar.positive { background: linear-gradient(180deg, #10b981, #047857); box-shadow: -2px 0 12px rgba(16, 185, 129, 0.5); }

        .clusters-header {
            display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 32px; flex-wrap: wrap; gap: 16px;
            padding-bottom: 24px; border-bottom: 1px solid rgba(255,255,255,0.05);
        }

        .clusters-stats-row {
            display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap;
            background: rgba(255,255,255,0.02); padding: 16px;
            border-radius: 16px; border: 1px solid rgba(255,255,255,0.05);
            backdrop-filter: blur(10px);
        }

        .cluster-stat-pill {
            display: inline-flex; align-items: center; gap: 10px;
            padding: 10px 20px; background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px;
            font-size: 14px; color: #d1d5db; transition: all 0.3s ease;
        }
        
        .cluster-stat-pill:hover {
            background: rgba(255, 255, 255, 0.08); transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }

        .cluster-stat-pill strong { color: #fff; font-family: 'JetBrains Mono', monospace; font-size: 16px; }

        .cluster-expand-icon {
            transition: transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            background: rgba(255,255,255,0.05); border-radius: 50%;
            padding: 4px; width: 28px; height: 28px;
        }
        
        .cluster-card:hover .cluster-expand-icon { background: rgba(255,255,255,0.1); }
        .cluster-card.expanded .cluster-expand-icon { transform: rotate(180deg); background: rgba(59, 130, 246, 0.2); color: #60a5fa; }

        @media (max-width: 768px) {
            .cluster-card { padding: 20px; border-radius: 16px; }
            .clusters-header { flex-direction: column; align-items: flex-start; }
        }
        
        @keyframes fadeUpIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .cluster-card.animate-in { animation: fadeUpIn 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards; opacity: 0; }
"""
content = re.sub(r"/\* ===== News Clustering Styles ===== \*/.*?(?=</style>)", css_new, content, flags=re.DOTALL)

# 2. Update Header HTML
html_header_old = r'''<div class="clusters-header">
                    <div>
                        <h2 class="font-serif text-3xl md:text-4xl text-white mb-2 flex items-center gap-3">
                            <span class="w-10 h-10 bg-gradient-to-br from-blue-500 via-cyan-500 to-emerald-500 rounded-xl flex items-center justify-center">
                                <i data-lucide="layers" class="w-5 h-5 text-white"></i>
                            </span>
                            الأحداث الجارية
                        </h2>
                        <p class="text-sm text-neutral-400">تجميع ذكي للأخبار المتشابهة من مصادر متعددة — انقر على أي حدث لرؤية التغطيات المختلفة</p>
                    </div>
                    <button onclick="refreshClusters()" class="px-4 py-2 bg-white/5 hover:bg-neon-blue/20 border border-white/10 hover:border-neon-blue/50 rounded-lg transition-all duration-300 flex items-center gap-2 text-xs text-neutral-300 hover:text-neon-blue">
                        <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                        <span>تحديث</span>
                    </button>
                </div>'''

html_header_new = r'''<div class="clusters-header">
                    <div>
                        <h2 class="font-serif text-3xl md:text-5xl text-white mb-3 flex items-center gap-4">
                            <span class="relative w-12 h-12 md:w-14 md:h-14 bg-gradient-to-br from-blue-600 via-cyan-500 to-emerald-400 rounded-2xl flex items-center justify-center shadow-[0_0_30px_rgba(45,212,191,0.3)] border border-white/20 backdrop-blur-md">
                                <i data-lucide="layers" class="w-6 h-6 md:w-7 md:h-7 text-white"></i>
                                <span class="absolute -right-1 -top-1 w-3 h-3 bg-red-500 rounded-full animate-ping"></span>
                                <span class="absolute -right-1 -top-1 w-3 h-3 bg-red-500 rounded-full border border-black"></span>
                            </span>
                            الأحداث الجارية
                        </h2>
                        <p class="text-sm md:text-base text-neutral-400 mt-2 max-w-2xl leading-relaxed">تجميع ذكي ومباشر للأخبار المتشابهة من مصادر متعددة باستخدام الذكاء الاصطناعي. انقر على أي حدث لرؤية تغطية أوسع.</p>
                    </div>
                    <button onclick="refreshClusters()" class="px-5 py-2.5 bg-white/5 hover:bg-neon-blue/20 border border-white/10 hover:border-neon-blue/50 rounded-xl transition-all duration-300 flex items-center gap-2 text-sm text-neutral-200 hover:text-neon-blue hover:shadow-[0_0_20px_rgba(45,212,191,0.2)] hover:-translate-y-1">
                        <i data-lucide="refresh-cw" class="w-4 h-4"></i>
                        <span class="font-bold tracking-wide">تحديث المُلخص</span>
                    </button>
                </div>'''

content = content.replace(html_header_old, html_header_new)

# 3. Update renderClusters function
js_old_start = "function renderClusters(clusters) {"
js_old_end = "function toggleCluster(idx) {"

js_new = """function renderClusters(clusters) {
            const grid = document.getElementById('clusters-grid');
            if (!grid) return;

            if (!clusters || clusters.length === 0) {
                grid.innerHTML = `
                    <div class="col-span-full text-center py-20">
                        <i data-lucide="inbox" class="w-16 h-16 mx-auto mb-4 text-neutral-700"></i>
                        <p class="text-neutral-400 text-lg mb-2">لا توجد أحداث مجمّعة حالياً</p>
                        <p class="text-neutral-600 text-sm">سيتم تجميع الأخبار عند توفر عدد كافٍ منها</p>
                    </div>
                `;
                return;
            }

            const intensityColors = {
                conflict: { glow: 'rgba(239, 68, 68, 0.4)', text: '#f87171', label: 'صراع وتوتر عالٍ' },
                crisis: { glow: 'rgba(245, 158, 11, 0.4)', text: '#fbbf24', label: 'أزمة سياسية' },
                important: { glow: 'rgba(59, 130, 246, 0.4)', text: '#60a5fa', label: 'حدث مهم' },
                positive: { glow: 'rgba(16, 185, 129, 0.4)', text: '#34d399', label: 'تطور إيجابي' }
            };

            const typeLabels = { world: '🎬 عالمي', yemen: '🇾🇪 يمني', newspaper: '📰 صحافة' };

            grid.innerHTML = clusters.map((cluster, idx) => {
                const intensity = intensityColors[cluster.intensity] || intensityColors.important;
                const isLarge = cluster.news_count >= 5;

                const sourceTags = cluster.sources.slice(0, 4).map(s =>
                    `<span class="cluster-source-tag">${s}</span>`
                ).join('');
                const extraSources = cluster.sources.length > 4 ? `<span class="cluster-source-tag">+${cluster.sources.length - 4}</span>` : '';

                const typeBadges = cluster.types.map(t =>
                    `<span class="cluster-type-dot ${t}" title="${typeLabels[t] || t}"></span>`
                ).join('');

                const newsListHtml = cluster.news.map(n => {
                    const typeColor = n.type === 'world' ? '#3b82f6' : n.type === 'yemen' ? '#10b981' : '#f59e0b';
                    const thumbSrc = n.image_url || '';
                    const thumbHtml = thumbSrc ? `<img src="${thumbSrc}" class="cluster-news-thumb" loading="lazy" onerror="this.style.display='none'">` : '';
                    const escapedLink = n.link.replace(/'/g, "\\\\'");
                    return `
                        <a href="${n.link}" target="_blank" rel="noopener" class="cluster-news-item group" onclick="event.stopPropagation()">
                            ${thumbHtml}
                            <div class="flex-1 min-w-0">
                                <div class="flex items-center gap-3 mb-2">
                                    <div class="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-white/5 border border-white/10">
                                        <span class="cluster-type-dot ${n.type}"></span>
                                        <span class="text-[10px] font-mono text-white opacity-80">${n.source}</span>
                                    </div>
                                    <span class="text-[10px] text-neutral-500 font-mono flex items-center gap-1">
                                        <i data-lucide="clock" class="w-2.5 h-2.5"></i>
                                        ${n.published ? new Date(n.published).toLocaleDateString('ar-EG', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : ''}
                                    </span>
                                </div>
                                <h4 class="text-[14px] font-bold text-neutral-200 leading-snug group-hover:text-neon-blue transition-colors line-clamp-2">${n.title}</h4>
                            </div>
                            <div class="flex items-center justify-center w-8 h-8 rounded-full bg-white/5 group-hover:bg-neon-blue/20 transition-colors mt-auto mb-auto ml-2 opacity-0 group-hover:opacity-100">
                                <i data-lucide="external-link" class="w-3.5 h-3.5 text-neutral-400 group-hover:text-neon-blue"></i>
                            </div>
                        </a>
                    `;
                }).join('');

                return `
                    <div class="cluster-card animate-in ${isLarge ? 'lg:col-span-2' : ''}" id="cluster-${idx}" onclick="toggleCluster(${idx})" style="animation-delay: ${idx * 0.1}s">
                        <div class="cluster-intensity-bar ${cluster.intensity}"></div>
                        
                        <div class="relative z-10">
                            <div class="flex items-start justify-between gap-4 mb-5">
                                <div class="flex items-center gap-4">
                                    <div class="cluster-count-badge shadow-lg">
                                        ${cluster.news_count}
                                    </div>
                                    <div class="flex flex-col gap-1">
                                        <span class="text-[11px] font-bold px-2.5 py-1 rounded-md bg-white/5 border border-white/10 w-fit" style="color: ${intensity.text}; text-shadow: 0 0 10px ${intensity.glow}">
                                            <i data-lucide="activity" class="w-3 h-3 inline-block mr-1"></i> ${intensity.label}
                                        </span>
                                        <span class="text-xs text-neutral-400 flex items-center gap-1"><i data-lucide="database" class="w-3 h-3"></i> مُجمّع من ${cluster.source_count} مصادر</span>
                                    </div>
                                </div>
                                <div class="flex items-center gap-3">
                                    <div class="flex gap-1.5 p-1.5 bg-black/20 rounded-full border border-white/5">
                                        ${typeBadges}
                                    </div>
                                    <div class="cluster-expand-icon flex items-center justify-center">
                                        <i data-lucide="chevron-down" class="w-4 h-4 text-neutral-300"></i>
                                    </div>
                                </div>
                            </div>

                            <h3 class="text-xl md:text-2xl font-serif font-bold text-white mb-4 leading-tight group-hover:text-transparent group-hover:bg-clip-text group-hover:bg-gradient-to-r group-hover:from-white group-hover:to-neutral-400 transition-all">${cluster.title}</h3>

                            <div class="flex flex-wrap gap-2 mb-2">
                                ${sourceTags}${extraSources}
                            </div>
                        </div>

                        <div class="cluster-news-list" id="cluster-list-${idx}">
                            <div class="border-t border-white/10 mt-5 pt-5 space-y-2">
                                ${newsListHtml}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
            
            // Add mousemove effect for glow
            document.querySelectorAll('.cluster-card').forEach(card => {
                card.addEventListener('mousemove', e => {
                    const rect = card.getBoundingClientRect();
                    const x = e.clientX - rect.left;
                    const y = e.clientY - rect.top;
                    card.style.setProperty('--mouse-x', `${x}px`);
                    card.style.setProperty('--mouse-y', `${y}px`);
                });
            });
        }
"""

content = re.sub(r"function renderClusters\(clusters\) \{.*?(?=function toggleCluster\(idx\))", js_new, content, flags=re.DOTALL)

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
print("Updated successfully")
