/* ============================================================
   进阶数学手册 · 阅读器
   ============================================================ */
(function () {
  'use strict';

  var DATA = window.BOOK_DATA || { meta: {}, toc: [], chapters: {} };
  var chapters = DATA.chapters;

  /* ---------- 扁平化目录 ---------- */
  var flat = [];
  (DATA.toc || []).forEach(function (vol) {
    (vol.chapters || []).forEach(function (ch) {
      flat.push({ id: ch.id, no: ch.no, title: ch.title, vol: vol.vol, built: !!chapters[ch.id] });
    });
  });
  var posOf = {};
  flat.forEach(function (c, i) { posOf[c.id] = i; });

  var $ = function (s) { return document.querySelector(s); };
  var elArticle = $('#article');
  var elSidebar = $('#sidebar');
  var elTocCol = $('#tocCol');
  var elPanel = $('#searchPanel');
  var elInput = $('#searchInput');
  var elProgress = $('#progress');

  var current = null;
  var scrollHandler = null;

  /* ---------- 工具 ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* ---------- 公式排版 ----------
     MathJax 就绪后统一走 typesetPromise；startup 被拒绝（某个扩展缺失）
     时也再试一次。若引擎最终没能挂上，交给 __mathFail 给出可见提示 ——
     宁可弹一条能点的提示，也不要留一页没人认识的 $…$。 */
  function mathOffline(err) {
    if (typeof window.__mathFail === 'function') window.__mathFail(err);
  }

  function typeset(el) {
    var run = function () {
      if (window.MathJax && window.MathJax.typesetPromise) {
        return window.MathJax.typesetPromise([el])
          .catch(function (e) { console.warn('MathJax:', e); });
      }
      return Promise.reject(new Error('MathJax.typesetPromise 不可用'));
    };
    var MJ = window.MathJax;
    // 首选 microtask 路径（不依赖计时器，任何环境下都可靠）
    if (MJ && MJ.startup && MJ.startup.promise) {
      return MJ.startup.promise.then(run, function () {
        // startup 被拒绝（例如某扩展缺失）时仍尝试一次
        return run();
      }).catch(mathOffline);
    }
    // 兜底：轮询等待 MathJax 挂载
    return new Promise(function (resolve) {
      var tries = 0;
      (function poll() {
        if (window.MathJax && window.MathJax.typesetPromise) {
          run().then(resolve, resolve);
        } else if (tries++ > 400) {
          mathOffline(new Error('脚本未加载：vendor/mathjax/tex-svg-full.js'));
          resolve();
        } else {
          setTimeout(poll, 50);
        }
      })();
    });
  }

  function parseHash(h) {
    h = (h || '').replace(/^#/, '');
    if (!h) return { cid: null, sub: null };
    if (chapters[h]) return { cid: h, sub: null };
    var m = h.match(/^(ch\d{2}|app[A-Z])-(\d+(?:-\d+)?)$/);
    if (m) return { cid: m[1], sub: h };
    var any = h.match(/^(ch\d{2}|app[A-Z])/);
    if (any) return { cid: any[1], sub: null };
    return { cid: null, sub: null };
  }

  /* ---------- 侧栏目录 ---------- */
  function renderSidebar() {
    var html = '';
    var lastVol = null;
    flat.forEach(function (c) {
      if (c.vol !== lastVol) {
        html += '<div class="vol-title">' + esc(c.vol) + '</div>';
        lastVol = c.vol;
      }
      if (c.built) {
        html += '<a class="ch-link" data-id="' + c.id + '" href="#' + c.id + '">' +
          '<span class="no">' + esc(c.no) + '</span><span>' + esc(c.title) + '</span></a>';
      } else {
        html += '<div class="ch-link pending" title="尚未撰写">' +
          '<span class="no">' + esc(c.no) + '</span><span>' + esc(c.title) + '</span>' +
          '<span class="badge">待写</span></div>';
      }
    });
    elSidebar.innerHTML = html;
  }

  function markActive(cid) {
    Array.prototype.forEach.call(elSidebar.querySelectorAll('.ch-link'), function (a) {
      a.classList.toggle('active', a.getAttribute('data-id') === cid);
    });
    var act = elSidebar.querySelector('.ch-link.active');
    if (act && act.scrollIntoView) {
      var r = act.getBoundingClientRect(), sr = elSidebar.getBoundingClientRect();
      if (r.top < sr.top + 40 || r.bottom > sr.bottom - 40) {
        act.scrollIntoView({ block: 'center' });
      }
    }
  }

  /* ---------- 右侧小节目录 + 滚动跟随 ---------- */
  function renderTocCol(headings) {
    if (!headings || !headings.length) { elTocCol.innerHTML = ''; return; }
    var h = '<h4>本章目录</h4>';
    headings.forEach(function (d) {
      h += '<a class="lv' + d.level + '" href="#' + d.id + '" data-id="' + d.id + '">' +
        esc(d.text) + '</a>';
    });
    elTocCol.innerHTML = h;
  }

  function bindScrollSpy() {
    if (scrollHandler) window.removeEventListener('scroll', scrollHandler);
    var links = Array.prototype.slice.call(elTocCol.querySelectorAll('a'));
    if (!links.length) return;
    var ticking = false;

    scrollHandler = function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;

        var doc = document.documentElement;
        var total = doc.scrollHeight - window.innerHeight;
        var p = total > 0 ? Math.min(1, Math.max(0, window.scrollY / total)) : 0;
        if (elProgress) elProgress.style.width = (p * 100) + '%';

        var best = null, bestTop = -1e9;
        links.forEach(function (a) {
          var t = document.getElementById(a.getAttribute('data-id'));
          if (!t) return;
          var top = t.getBoundingClientRect().top - 90;
          if (top <= 0 && top > bestTop) { bestTop = top; best = a; }
        });
        links.forEach(function (a) { a.classList.toggle('on', a === best); });
      });
    };
    window.addEventListener('scroll', scrollHandler, { passive: true });
    scrollHandler();
  }

  /* ---------- ASCII 图栅格对齐 ----------
     图是按「西文 1 列、CJK 2 列」排的，但 CJK 实际只有 1.84 倍宽，
     含中文的行会比纯框线行短，方框右缘参差（17 行能测出 9 种宽度）。
     靠字体修不了（local() 字体的 size-adjust 不生效）。
     这里把图内每个「非 ASCII 且非制表符」的字符都包进固定宽度的
     <i>：实测宽度 ≥ 1.5 列用 2ch，否则 1ch —— 与字体无关，绝对精确。
     ⚠ 制表符 U+2500–257F 不包（本就半角，且参与框线拼接）。
     ⚠ 换行/回车/制表符必须排除：它们是控制字符，也在上面那个
       「非 ASCII 可打印」补集里。一旦把 \n 包进 <i>，行断点就变成
       一个 inline-block 原子盒，整张图会被排成一条横向长线
       （pre 撑出几万像素、只能横向滚动），纵向层级全部消失。   */
  var RE_GRID_WRAP = /[^\t\n\r\x20-\x7E\u2500-\u257F]/g;
  var RE_BOXDRAW = /[\u2500-\u257F]/;   /* 带框线 → 这是图，不是代码 */

  function alignAsciiGrids(root) {
    var sample = root.querySelector('.code-block code');
    if (!sample) return;
    var cs = window.getComputedStyle(sample);
    var ctx = document.createElement('canvas').getContext('2d');
    ctx.font = cs.fontSize + ' ' + cs.fontFamily;
    var unit = ctx.measureText('0').width || 7.62;
    var cache = {};

    function boxOf(ch) {
      if (ch in cache) return cache[ch];
      var r = ctx.measureText(ch).width / unit;
      return (cache[ch] = r >= 1.5 ? 2 : 1);
    }

    var blocks = root.querySelectorAll('.code-block code');
    for (var i = 0; i < blocks.length; i++) {
      var el = blocks[i];
      if (el.getAttribute('data-grid') === '1') continue;
      el.setAttribute('data-grid', '1');
      /* 图里的 │ ─ 要靠上下行首尾相接才连成实线，代码块的宽松行距
         （1.65em）会把它们拉成虚线。含框线的块打上 ascii-grid，
         由 css 单独收紧行距；普通代码块不受影响。 */
      if (el.parentElement && RE_BOXDRAW.test(el.textContent)) {
        (el.closest('.code-block') || el.parentElement).classList.add('ascii-grid');
      }
      el.innerHTML = el.innerHTML.replace(RE_GRID_WRAP, function (ch) {
        return '<i class="fw' + boxOf(ch) + '">' + ch + '</i>';
      });
    }
  }

  /* ---------- 渲染一章 ---------- */
  function renderChapter(cid) {
    var c = chapters[cid];
    if (!c) return;

    var i = posOf[cid];
    var prev = null, next = null, k;
    for (k = i - 1; k >= 0; k--) { if (flat[k].built) { prev = flat[k]; break; } }
    for (k = i + 1; k < flat.length; k++) { if (flat[k].built) { next = flat[k]; break; } }

    var html = '';
    html += '<header class="ch-head">' +
      '<div class="eyebrow">' + esc(c.volume) + '</div>' +
      '<h1>' + (c.no === '0' ? '' : '第 ' + esc(c.no) + ' 章　') + esc(c.title) + '</h1>' +
      '<div class="meta"><span>约 ' + (c.chars >= 10000 ? (c.chars / 10000).toFixed(1) + ' 万字' : (c.chars / 1000).toFixed(1) + ' 千字') + '</span>' +
      '<span>' + c.formulas + ' 处公式</span>' +
      '<span>' + c.headings.length + ' 个小节</span></div>' +
      '</header>';

    html += '<div class="prose">' + c.html + '</div>';

    html += '<nav class="pager">';
    html += prev
      ? '<a class="prev" href="#' + prev.id + '"><small>上一章</small>' + esc(prev.title) + '</a>'
      : '<a class="prev" style="visibility:hidden"></a>';
    html += next
      ? '<a class="next" href="#' + next.id + '"><small>下一章</small>' + esc(next.title) + '</a>'
      : '<a class="next" href="#welcome"><small>返回</small>全书总览</a>';
    html += '</nav>';

    elArticle.innerHTML = html;
    current = cid;
    markActive(cid);
    renderTocCol(c.headings);
    document.title = c.title + ' · ' + DATA.meta.title;
    alignAsciiGrids(elArticle);
    return typeset(elArticle);
  }

  /* ---------- 欢迎页 ---------- */
  function renderWelcome() {
    var totalChars = 0, done = 0;
    flat.forEach(function (c) { if (c.built) { done++; totalChars += chapters[c.id].chars; } });

    var html = '';
    html += '<header class="ch-head"><div class="eyebrow">' + esc(DATA.meta.edition) + '</div>' +
      '<h1>' + esc(DATA.meta.title) + '</h1>' +
      '<div class="meta"><span>' + esc(DATA.meta.subtitle) + '</span></div></header>';

    html += '<div class="welcome">';
    html += '<p class="lead">这是一部<b>面向信号处理、控制、机器学习与泛化理论</b>的数学进阶手册。' +
      '正文只讲<b>概念、方法、公式、应用</b>四件事，程序与数值工具收在附录速查，不占主线。' +
      '全书共 <b>' + flat.length + '</b> 个章节单元，目前已完稿 <b>' + done + '</b> 个单元、约 <b>' +
      Math.round(totalChars / 1000) + ' 千字</b>。</p>';

    html += '<h2 style="font-family:var(--font-ui);font-size:19px;margin:34px 0 14px;color:var(--text)">推荐学习路径</h2>';
    html += '<div class="cards">';
    var paths = [
      ['控制路线', '0 → 1 → 5 → 13 → 14 → 16 → 17 → 18 → 19 → 20 → 21 → 22 → 24 → 25 → 30 → 34 → 36'],
      ['鲁棒控制专线', '0 → 5 → 6 → 14 → 17 → 18 → 20 → 30 → 33 → 34 → 36'],
      ['信号路线', '0 → 1 → 2 → 4 → 5 → 12 → 13 → 14 → 15 → 30 → 31 → 36'],
      ['学习 / 泛化路线', '0 → 1 → 2 → 3 → 6 → 7 → 8 → 28 → 11 → 25 → 33 → 35 → 36'],
      ['深度学习理论路线', '0 → 1 → 2 → 3 → 6 → 7 → 8 → 25 → 26 → 27 → 29 → 36']
    ];
    paths.forEach(function (p) {
      html += '<div class="card"><h4>' + esc(p[0]) + '</h4><p class="path">' + esc(p[1]) + '</p></div>';
    });
    html += '</div>';

    html += '<h2 style="font-family:var(--font-ui);font-size:19px;margin:40px 0 14px;color:var(--text)">已完稿章节</h2>';
    html += '<div class="cards">';
    flat.forEach(function (c) {
      if (!c.built) return;
      html += '<div class="card" onclick="location.hash=\'#' + c.id + '\'">' +
        '<h4>' + (c.no === '0' ? '' : '第 ' + esc(c.no) + ' 章　') + esc(c.title) + '</h4>' +
        '<p>' + esc(c.vol) + '</p>' +
        '<p class="path">' + chapters[c.id].headings.filter(function (h) { return h.level === 2; })
          .map(function (h) { return h.text; }).join(' · ') + '</p></div>';
    });
    html += '</div>';

    html += '<p style="margin-top:36px;font-size:13px;color:var(--text-faint)">' +
      '构建时间 ' + esc(DATA.builtAt) + '　·　按 <b>/</b> 键搜索全书　·　按 <b>Esc</b> 键关闭搜索</p>';
    html += '</div>';

    elArticle.innerHTML = html;
    current = null;
    markActive(null);
    renderTocCol([]);
    elProgress.style.width = '0';
    document.title = DATA.meta.title + ' · ' + DATA.meta.subtitle;
  }

  /* ---------- 路由 ---------- */
  function scrollToTarget(sub) {
    var t = sub ? document.getElementById(sub) : null;
    if (!t) { window.scrollTo(0, 0); return; }
    // 等两帧，确保 MathJax 排版引起的 reflow 完成后再定位
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var y = t.getBoundingClientRect().top + window.scrollY - 70;
        window.scrollTo(0, Math.max(0, y));
      });
    });
  }

  function route(scrollTarget) {
    var p = parseHash(location.hash);
    var need;
    if (!p.cid) {
      if (current !== null || !elArticle.innerHTML) renderWelcome();
      if (scrollTarget) window.scrollTo(0, 0);
      return;
    }
    if (p.cid !== current) {
      need = renderChapter(p.cid);
    } else {
      need = Promise.resolve();
    }
    need.then(function () {
      if (scrollTarget) scrollToTarget(p.sub);
      bindScrollSpy();
    });
  }

  /* ---------- 搜索 ---------- */
  var searchIndex = null;
  function buildIndex() {
    if (searchIndex) return searchIndex;
    searchIndex = [];
    Object.keys(chapters).forEach(function (cid) {
      var c = chapters[cid];
      var d = document.createElement('div');
      d.innerHTML = c.html;
      var text = (d.textContent || '').replace(/\s+/g, ' ').trim();
      searchIndex.push({ id: cid, no: c.no, title: c.title, text: text });
    });
    return searchIndex;
  }

  function doSearch(q) {
    q = q.trim();
    if (q.length < 2) {
      document.body.classList.remove('searching');
      return;
    }
    var idx = buildIndex();
    var lq = q.toLowerCase();
    var out = [];
    idx.forEach(function (rec) {
      var lower = rec.text.toLowerCase();
      var from = 0, hits = [], n;
      while ((n = lower.indexOf(lq, from)) !== -1 && hits.length < 4) {
        hits.push(n);
        from = n + lq.length;
      }
      if (hits.length) out.push({ rec: rec, hits: hits, count: (lower.split(lq).length - 1) });
    });
    out.sort(function (a, b) { return b.count - a.count; });

    var html = '<h3>搜索「' + esc(q) + '」　命中 ' + out.length + ' 章</h3>';
    if (!out.length) {
      html += '<div class="empty">未找到匹配内容。可尝试更短的关键词，或换用公式的英文名（如 Gamma、Riccati、Nyquist）。</div>';
    }
    out.forEach(function (o) {
      html += '<div class="hit" data-id="' + o.rec.id + '">' +
        '<div class="hit-ch">第 ' + esc(o.rec.no) + ' 章　' + esc(o.rec.title) + '　(' + o.count + ' 处)</div>';
      o.hits.forEach(function (n) {
        var s = Math.max(0, n - 52), e = Math.min(o.rec.text.length, n + q.length + 68);
        var seg = esc(o.rec.text.slice(s, e))
          .replace(new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), function (m) { return '<mark>' + m + '</mark>'; });
        html += '<div class="hit-tx">' + (s > 0 ? '…' : '') + seg + (e < o.rec.text.length ? '…' : '') + '</div>';
      });
      html += '</div>';
    });
    elPanel.innerHTML = html;
    document.body.classList.add('searching');
  }

  function closeSearch() {
    document.body.classList.remove('searching');
    elInput.blur();
  }

  /* ---------- 两栏的开合状态 ----------
     宽屏（>900px）左右两栏都能收起，状态记在 localStorage，下次打开
     还是上次的样子；窄屏不做记忆 —— 左栏在那里是抽屉，进页面就该是
     关着的。按钮上用 aria-pressed 反映当前状态，样式表照着上色。 */
  var LAYOUT_KEY = 'amh-layout';
  var layout = (function () {
    try { return JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}') || {}; }
    catch (e) { return {}; }
  })();

  function saveLayout() {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch (e) {}
  }

  function isNarrow() {
    return window.matchMedia
      ? window.matchMedia('(max-width: 900px)').matches
      : window.innerWidth <= 900;
  }

  function applyLayout() {
    if (isNarrow()) {
      document.body.classList.remove('nav-collapsed', 'toc-collapsed');
    } else {
      document.body.classList.toggle('nav-collapsed', !!layout.nav);
      document.body.classList.toggle('toc-collapsed', !!layout.toc);
    }
    var nb = $('#btnNav'), tb = $('#btnToc');
    if (nb) nb.setAttribute('aria-pressed', String(document.body.classList.contains('nav-collapsed')));
    if (tb) tb.setAttribute('aria-pressed', String(document.body.classList.contains('toc-collapsed')));
  }

  /* ---------- 事件绑定 ---------- */
  function bind() {
    if (elInput) {
      var timer = null;
      elInput.addEventListener('input', function () {
        clearTimeout(timer);
        var v = elInput.value;
        timer = setTimeout(function () { doSearch(v); }, 140);
      });
      elInput.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { elInput.value = ''; closeSearch(); }
      });
    }

    if (elPanel) {
      elPanel.addEventListener('click', function (e) {
        var hit = e.target.closest ? e.target.closest('.hit') : null;
        if (hit) {
          location.hash = '#' + hit.getAttribute('data-id');
          closeSearch();
          if (elInput) elInput.value = '';
        }
      });
    }

    document.addEventListener('keydown', function (e) {
      if (e.key === '/' && document.activeElement !== elInput) {
        e.preventDefault();
        if (elInput) elInput.focus();
      }
      if (e.key === 'Escape') closeSearch();
    });

    document.addEventListener('click', function (e) {
      var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (a && a.classList.contains('ch-link')) {
        document.body.classList.remove('nav-open');
      }
      if (a && a.classList.contains('anchor')) {
        e.preventDefault();
        history.replaceState(null, '', a.getAttribute('href'));
        var t = document.getElementById(a.getAttribute('href').slice(1));
        if (t) t.scrollIntoView({ block: 'start' });
      }
    });

    /* 左栏按钮：窄屏开合抽屉，宽屏收起整列 —— 同一个按钮，两种语义 */
    var btnNav = $('#btnNav');
    if (btnNav) btnNav.addEventListener('click', function () {
      if (isNarrow()) {
        document.body.classList.toggle('nav-open');
      } else {
        layout.nav = !document.body.classList.contains('nav-collapsed');
        saveLayout();
        applyLayout();
      }
    });

    var btnToc = $('#btnToc');
    if (btnToc) btnToc.addEventListener('click', function () {
      layout.toc = !document.body.classList.contains('toc-collapsed');
      saveLayout();
      applyLayout();
    });

    var scrim = $('#scrim');
    if (scrim) scrim.addEventListener('click', function () { document.body.classList.remove('nav-open'); });

    /* 跨过 900px 时切换语义：抽屉状态清掉，宽屏折叠状态重新按记忆铺上 */
    var mqNarrow = window.matchMedia ? window.matchMedia('(max-width: 900px)') : null;
    if (mqNarrow) {
      var onMq = function () { document.body.classList.remove('nav-open'); applyLayout(); };
      if (mqNarrow.addEventListener) mqNarrow.addEventListener('change', onMq);
      else if (mqNarrow.addListener) mqNarrow.addListener(onMq);
    }

    window.addEventListener('hashchange', function () { route(true); });
  }

  /* ---------- 启动 ---------- */
  renderSidebar();
  applyLayout();
  bind();
  route(true);
})();
