/* 涨停次日接力观察池 · 交互逻辑（零依赖，原生 SVG 绘图） */
(function () {
  'use strict';

  var D = window.__DASHBOARD_DATA__ || null;
  var HIST = window.__HISTORY__ || { days: [] };
  var $ = function (id) { return document.getElementById(id); };
  var UP = 'var(--up)', DOWN = 'var(--down)', ACC = 'var(--accent)',
      BORDER = 'var(--border)', TXT2 = 'var(--text-2)', TXT3 = 'var(--text-3)',
      SURF3 = 'var(--surface-3)';

  function esc(s) {
    return String(s === null || s === undefined ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function num(v, d) {
    if (v === null || v === undefined || v === '' || isNaN(Number(v))) return '--';
    return Number(v).toFixed(d === undefined ? 2 : d);
  }
  function signed(v, d, suffix) {
    if (v === null || v === undefined || isNaN(Number(v))) return '--';
    var n = Number(v);
    return (n > 0 ? '+' : '') + n.toFixed(d === undefined ? 2 : d) + (suffix || '');
  }
  function tone(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return 'muted';
    return Number(v) > 0 ? 'pos' : Number(v) < 0 ? 'neg' : 'muted';
  }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function srcNote(extra) {
    var m = D.meta;
    return '<p class="src-note">数据来源：' + esc(m.source) + '｜时点 ' + esc(m.as_of) +
      '（北京时间，' + esc(m.market_status) + '）' + (extra ? '｜' + extra : '') +
      '。主力资金为按成交单笔金额推断的统计量，非交易所席位数据。</p>';
  }

  var state = {
    tab: 'pool',
    theme: localStorage.getItem('relay-theme') || 'light',
    rows: [],
    weights: {},
    customWeights: false,
    grades: { A: 75, B: 65, C: 55 },
    filters: { q: '', grade: 'ALL', board: 'ALL', industry: 'ALL', minScore: 55, sort: 'score' },
    flowView: 'chart'
  };

  /* ---------------- SVG 图表 ---------------- */
  function svgBarH(items, opts) {
    opts = opts || {};
    var W = 680, rowH = opts.rowH || 26, padT = 12, padB = 8,
        padL = opts.labelW || 118, padR = opts.padR || 66;
    var H = padT + padB + items.length * rowH;
    var vals = items.map(function (i) { return Number(i.value) || 0; });
    var max = Math.max.apply(null, vals.concat([0]));
    var min = Math.min.apply(null, vals.concat([0]));
    var span = (max - min) || 1;
    var inner = W - padL - padR;
    var zeroX = padL + (0 - min) / span * inner;
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="横向条形图">';
    items.forEach(function (it, idx) {
      // 空值不画柱子：否则资金缺数据时会画出一条 0 长度的「净额为 0」假象
      var raw = it.value;
      var has = raw !== null && raw !== undefined && raw !== '' && !isNaN(Number(raw));
      var v = has ? Number(raw) : 0;
      var y = padT + idx * rowH + 3, h = rowH - 9;
      var x2 = padL + (v - min) / span * inner;
      var x = Math.min(zeroX, x2), w = Math.max(2, Math.abs(x2 - zeroX));
      var color = it.color || (v >= 0 ? UP : DOWN);
      s += '<text x="' + (padL - 8) + '" y="' + (y + h / 2 + 4) + '" text-anchor="end" ' +
           'style="fill:' + TXT2 + ';font-size:11.5px">' + esc(it.label) + '</text>';
      s += '<rect x="' + padL + '" y="' + y + '" width="' + inner + '" height="' + h + '" rx="3" ' +
           'style="fill:' + SURF3 + ';opacity:.55" />';
      if (has) {
        s += '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="3" ' +
             'style="fill:' + color + '" data-tip="' + esc(it.tip || (it.label + '：' + v)) + '" />';
      }
      s += '<text x="' + (W - 4) + '" y="' + (y + h / 2 + 4) + '" text-anchor="end" ' +
           'style="fill:' + (has ? (v >= 0 ? UP : DOWN) : TXT3) + ';font-size:11px;font-weight:600">' +
           esc(has ? (it.text || num(v, 2)) : '--') + '</text>';
    });
    return s + '</svg>';
  }

  function svgGroupedBars(groups, series, opts) {
    opts = opts || {};
    var W = 680, H = opts.height || 290, padL = 48, padR = 14, padT = 16, padB = 46;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var all = [];
    groups.forEach(function (g) { g.values.forEach(function (v) { all.push(Number(v) || 0); }); });
    var max = Math.max.apply(null, all.concat([0]));
    var min = Math.min.apply(null, all.concat([0]));
    var span = (max - min) || 1;
    var zeroY = padT + (max / span) * plotH;
    var scale = plotH / span;
    var gw = plotW / Math.max(1, groups.length);
    var bw = Math.max(3, Math.min(16, gw / (series.length + 1.4)));
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="分组柱状图">';
    [max, max / 2, 0, min / 2, min].forEach(function (v, i) {
      if (i === 2 && min === 0) return;
      var y = padT + (max - v) / span * plotH;
      s += '<line x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y +
           '" style="stroke:' + BORDER + ';stroke-width:1;stroke-dasharray:' + (v === 0 ? '0' : '3 3') + '" />';
      s += '<text x="' + (padL - 6) + '" y="' + (y + 4) + '" text-anchor="end" style="fill:' +
           TXT3 + ';font-size:10px">' + num(v, 1) + '</text>';
    });
    groups.forEach(function (g, gi) {
      var gx = padL + gi * gw + (gw - bw * series.length) / 2;
      g.values.forEach(function (raw, si) {
        var v = Number(raw) || 0;
        var y = v >= 0 ? zeroY - v * scale : zeroY;
        var h = Math.max(1.5, Math.abs(v) * scale);
        s += '<rect x="' + (gx + si * bw) + '" y="' + y + '" width="' + (bw - 2) + '" height="' + h +
             '" rx="2" style="fill:' + series[si].color + '" data-tip="' +
             esc(g.label + ' · ' + series[si].name + '：' + num(v, 2) + (opts.unit || '')) + '" />';
      });
      s += '<text x="' + (padL + gi * gw + gw / 2) + '" y="' + (H - padB + 16) +
           '" text-anchor="middle" style="fill:' + TXT2 + ';font-size:10.5px">' + esc(g.label) + '</text>';
    });
    var lx = padL;
    series.forEach(function (se) {
      s += '<rect x="' + lx + '" y="' + (H - 16) + '" width="9" height="9" rx="2" style="fill:' + se.color + '" />';
      s += '<text x="' + (lx + 13) + '" y="' + (H - 8) + '" style="fill:' + TXT2 + ';font-size:10.5px">' +
           esc(se.name) + '</text>';
      lx += 22 + se.name.length * 12;
    });
    return s + '</svg>';
  }

  function svgRadar(values, labels) {
    var W = 340, H = 300, cx = 170, cy = 148, R = 100, n = values.length;
    function pt(i, r) {
      var a = -Math.PI / 2 + i * 2 * Math.PI / n;
      return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
    }
    function poly(radius) {
      return values.map(function (_, i) { return pt(i, radius).join(','); }).join(' ');
    }
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="因子雷达图">';
    [0.25, 0.5, 0.75, 1].forEach(function (f) {
      s += '<polygon points="' + poly(R * f) + '" style="fill:none;stroke:' + BORDER + ';stroke-width:1" />';
    });
    values.forEach(function (_, i) {
      var p = pt(i, R);
      s += '<line x1="' + cx + '" y1="' + cy + '" x2="' + p[0] + '" y2="' + p[1] +
           '" style="stroke:' + BORDER + ';stroke-width:1" />';
      var lp = pt(i, R + 22);
      var anchor = Math.abs(lp[0] - cx) < 12 ? 'middle' : (lp[0] > cx ? 'start' : 'end');
      s += '<text x="' + lp[0] + '" y="' + (lp[1] + 4) + '" text-anchor="' + anchor +
           '" style="fill:' + TXT2 + ';font-size:10.5px">' + esc(labels[i]) + '</text>';
    });
    var dpts = values.map(function (v, i) { return pt(i, R * (Number(v) || 0) / 100).join(','); }).join(' ');
    s += '<polygon points="' + dpts + '" style="fill:' + ACC + ';fill-opacity:.18;stroke:' + ACC + ';stroke-width:2" />';
    values.forEach(function (v, i) {
      var p = pt(i, R * (Number(v) || 0) / 100);
      s += '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="3" style="fill:' + ACC +
           '" data-tip="' + esc(labels[i] + '：' + num(v, 1) + ' 分') + '" />';
    });
    return s + '</svg>';
  }

  function svgHistory(days) {
    var W = 680, H = 240, padL = 44, padR = 44, padT = 18, padB = 34;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var vals1 = days.map(function (d) { return Number(d.limit_up) || 0; });
    var vals2 = days.map(function (d) { return Number(d.break_rate) || 0; });
    var m1 = Math.max.apply(null, vals1.concat([10])) * 1.15;
    var m2 = Math.max.apply(null, vals2.concat([10])) * 1.15;
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="情绪时间序列">';
    [0, 0.5, 1].forEach(function (f) {
      var y = padT + (1 - f) * plotH;
      s += '<line x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y +
           '" style="stroke:' + BORDER + ';stroke-width:1" />';
      s += '<text x="' + (padL - 6) + '" y="' + (y + 4) + '" text-anchor="end" style="fill:' + TXT3 +
           ';font-size:10px">' + Math.round(m1 * f) + '</text>';
      s += '<text x="' + (W - padR + 6) + '" y="' + (y + 4) + '" style="fill:' + TXT3 +
           ';font-size:10px">' + Math.round(m2 * f) + '%</text>';
    });
    function path(vals, maxv, color) {
      return vals.map(function (v, i) {
        var x = padL + (days.length === 1 ? plotW / 2 : i / (days.length - 1) * plotW);
        var y = padT + (1 - v / maxv) * plotH;
        return (i ? 'L' : 'M') + x.toFixed(1) + ',' + y.toFixed(1);
      }).join(' ');
    }
    s += '<path d="' + path(vals1, m1, UP) + '" style="fill:none;stroke:' + UP + ';stroke-width:2" />';
    s += '<path d="' + path(vals2, m2, ACC) + '" style="fill:none;stroke:' + ACC + ';stroke-width:2;stroke-dasharray:5 3" />';
    days.forEach(function (d, i) {
      var x = padL + (days.length === 1 ? plotW / 2 : i / (days.length - 1) * plotW);
      var y1 = padT + (1 - (Number(d.limit_up) || 0) / m1) * plotH;
      var y2 = padT + (1 - (Number(d.break_rate) || 0) / m2) * plotH;
      s += '<circle cx="' + x + '" cy="' + y1 + '" r="3.5" style="fill:' + UP + '" data-tip="' +
           esc(d.date + ' 涨停 ' + d.limit_up + ' 家') + '" />';
      s += '<circle cx="' + x + '" cy="' + y2 + '" r="3.5" style="fill:' + ACC + '" data-tip="' +
           esc(d.date + ' 炸板率 ' + num(d.break_rate, 1) + '%') + '" />';
      if (days.length <= 12 || i % Math.ceil(days.length / 10) === 0) {
        s += '<text x="' + x + '" y="' + (H - 10) + '" text-anchor="middle" style="fill:' + TXT3 +
             ';font-size:9.5px">' + esc(String(d.date).slice(5)) + '</text>';
      }
    });
    s += '<text x="' + padL + '" y="' + (H - 1) + '" style="fill:' + UP + ';font-size:10px">■ 涨停家数（左轴）</text>';
    s += '<text x="' + (padL + 120) + '" y="' + (H - 1) + '" style="fill:' + ACC + ';font-size:10px">┄ 炸板率（右轴）</text>';
    return s + '</svg>';
  }

  /* ---------------- 评分重算 ---------------- */
  function reRank(rows, w) {
    if (!rows.length) return [];
    var keys = Object.keys(rows[0].factors);
    var sum = keys.reduce(function (a, k) { return a + (Number(w[k]) || 0); }, 0) || 1;
    var out = rows.map(function (r) {
      var base = 0;
      keys.forEach(function (k) {
        base += (Number(r.factors[k]) || 0) * (Number(w[k]) || 0);
      });
      base = base / sum + (Number(r.penalty_total) || 0);
      var score = Math.round(Math.max(0, Math.min(100, base)) * 10) / 10;
      var g = score >= state.grades.A ? 'A' : score >= state.grades.B ? 'B' :
              score >= state.grades.C ? 'C' : 'D';
      var x = Object.assign({}, r);
      x.score = score; x.grade = g;
      x.grade_label = { A: '重点观察', B: '备选观察', C: '谨慎观察', D: '不纳入' }[g];
      return x;
    });
    out.sort(function (a, b) { return b.score - a.score; });
    out.forEach(function (r, i) { r.rank = i + 1; });
    return out;
  }

  /* ---------------- 顶部与结论 ---------------- */
  function renderHeader() {
    document.documentElement.setAttribute('data-theme', state.theme);
    $('themeBtn').textContent = state.theme === 'light' ? '◐' : '☀';
    if (D.meta.is_stale || D.meta.is_demo) {
      $('demoBanner').classList.remove('hidden');
      $('demoBanner').textContent = '⚠ ' +
        (D.meta.stale_note || D.meta.demo_note || '非当前行情数据');
    } else {
      $('demoBanner').classList.add('hidden');
    }
    var m = D.meta, s = D.sentiment;
    var qMap = { full: '主源完整', partial: '备用源·部分口径', minimal: '备用源·量价口径', unknown: '口径未知' };
    var qLabel = qMap[m.quality] || m.quality || '口径未知';
    var qStyle = m.degraded ? ' style="color:var(--up);border-color:var(--up)"' : '';
    var asOf = String(m.as_of || '').replace(/\s*[+-]\d{4}\s*$/, '');
    $('sourceBar').innerHTML =
      '<span class="tag ' + (m.market_status === '盘中' ? 'live' : '') + '">' + esc(m.market_status) + '</span>' +
      '<span>交易日 <b>' + esc(m.date) + '</b></span>' +
      '<span>数据时点 ' + esc(asOf) + '（北京时间）</span>' +
      '<span class="sb-source">来源 ' + esc(m.source) + '</span>' +
      '<span class="tag"' + qStyle + '>数据源 ' + esc(qLabel) + '</span>' +
      '<span>策略版本 ' + esc(m.version) + '</span>';

    var emotionCls = (s.level === '退潮' || s.level === '分歧') ? 'calm' :
                     (s.level === '亢奋' || s.level === '活跃') ? '' : 'neutral';
    var lead = D.sectors.length ? D.sectors[0] : null;
    $('tldr').innerHTML =
      '<div class="tldr-head"><h2>今日结论：' + esc(s.level) + '，接力环境' +
      (s.level === '活跃' || s.level === '亢奋' ? '相对友好' :
       s.level === '退潮' ? '明显转弱' : '需精选') + '</h2>' +
      '<span class="badge ' + emotionCls + '">情绪评分 ' + s.score + '</span>' +
      (s.ladder_gap ? '<span class="badge neutral">梯队出现断层</span>' : '') + '</div>' +
      '<p>' + esc(s.note) + '。全市场涨停 ' + s.limit_up + ' 家、炸板 ' + s.broken +
      ' 家、跌停 ' + s.limit_down + ' 家，最高 ' + s.max_board + ' 板；' +
      '模型筛出 A 档 <b>' + D.candidates.filter(function (c) { return c.grade === 'A'; }).length +
      '</b> 只，' + (lead ? '涨停最集中的方向是 <b>' + esc(lead.industry) + '</b>（' + lead.count + ' 家，领涨 ' + esc(lead.leader) + '）' : '暂无明显主流方向') + '。</p>' +
      '<div class="tldr-meta"><span>判断依据：' + esc(s.basis) + '</span></div>';

    var aCount = D.candidates.filter(function (c) { return c.grade === 'A'; }).length;
    var topFlow = D.flow_leaders.length ? D.flow_leaders[0] : null;
    var kpis = [
      { l: '涨停家数', v: s.limit_up, sub: '通过筛选 ' + D.candidates.length + ' 只', c: 'pos' },
      { l: '炸板 / 炸板率', v: s.broken, sub: (s.break_rate === null ? '--' : s.break_rate + '%') + ' 曾开板回落', c: 'neg' },
      { l: '跌停家数', v: s.limit_down, sub: '风险偏好反向指标', c: 'neg' },
      { l: '最高连板', v: s.max_board + ' 板', sub: s.ladder_gap ? '梯队存在断层' : '梯队相对完整', c: '' },
      { l: 'A 档重点观察', v: aCount, sub: '共 ' + D.candidates.length + ' 只通过筛选', c: 'pos' },
      { l: '主力净流入居首', v: topFlow ? num(topFlow.main_net_yi, 2) + '亿' : '--',
        sub: topFlow ? esc(topFlow.name + ' · ' + topFlow.industry) : '暂无数据', c: topFlow && topFlow.main_net_yi > 0 ? 'pos' : '' }
    ];
    $('kpiGrid').innerHTML = kpis.map(function (k) {
      return '<div class="kpi"><div class="k-label">' + k.l + '</div><div class="k-value ' + k.c +
             '">' + k.v + '</div><div class="k-sub">' + k.sub + '</div></div>';
    }).join('');
    $('footer').innerHTML = '<b>' + esc(D.meta.strategy) + '</b> · 数据来源：' + esc(D.meta.source) +
      '｜时点 ' + esc(D.meta.as_of) + '<br>' + esc(D.meta.disclaimer) +
      '<br>主力资金（大单+超大单）系按成交单笔金额推断的统计量，非交易所席位真实资金；' +
      '本页所有评分与分档仅为研究排序，不构成任何买卖建议。';
  }

  /* ---------------- 筛选侧栏 ---------------- */
  function renderWeights() {
    var labels = D.config.factor_labels;
    $('weightSliders').innerHTML = Object.keys(D.config.weights).map(function (k) {
      return '<div class="weight-row"><div class="wr-top"><span>' + esc(labels[k] || k) +
             '</span><b>' + state.weights[k] + '</b></div>' +
             '<input type="range" min="0" max="40" step="1" value="' + state.weights[k] +
             '" data-weight="' + esc(k) + '"></div>';
    }).join('');
  }

  function renderIndustries() {
    var opts = ['<option value="ALL">全部行业</option>'].concat(D.sectors.map(function (s) {
      return '<option value="' + esc(s.industry) + '">' + esc(s.industry) + '（' + s.count + '）</option>';
    }));
    $('industryFilter').innerHTML = opts.join('');
  }

  function filteredRows() {
    var f = state.filters;
    var q = f.q.trim().toLowerCase();
    var rows = state.rows.filter(function (r) {
      if (r.score < f.minScore) return false;
      if (f.grade !== 'ALL' && r.grade !== f.grade) return false;
      if (f.board !== 'ALL') {
        if (f.board === '4' && r.boards < 4) return false;
        if (f.board !== '4' && r.boards !== Number(f.board)) return false;
      }
      if (f.industry !== 'ALL' && r.industry !== f.industry) return false;
      if (q && (r.code + ' ' + r.name + ' ' + r.industry).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    if (f.sort !== 'score') {
      rows.sort(function (a, b) { return (Number(b[f.sort]) || 0) - (Number(a[f.sort]) || 0); });
    }
    return rows;
  }

  function renderPool() {
    var rows = filteredRows();
    $('listCount').textContent = '共 ' + rows.length + ' 只';
    $('listSub').textContent = '点击任意一行查看评分拆解、资金结构与次日观察要点' +
      (state.customWeights ? ' · 当前使用自定义权重' : '');
    $('minScoreVal').textContent = state.filters.minScore;
    $('poolEmpty').classList.toggle('hidden', rows.length > 0);
    $('poolTable').parentElement.classList.toggle('hidden', rows.length === 0);

    $('poolBody').innerHTML = rows.map(function (r) {
      return '<tr data-code="' + esc(r.code) + '">' +
        '<td class="muted">' + r.rank + '</td>' +
        '<td><span class="stock-name">' + esc(r.name) + '</span><span class="stock-code">' + esc(r.code) + '</span></td>' +
        '<td><span class="score-cell"><span class="grade-tag grade-' + r.grade + '">' + r.grade + '</span>' +
        '<span class="score-bar"><i style="width:' + r.score + '%"></i></span><b>' + num(r.score, 1) + '</b></span></td>' +
        '<td>' + r.boards + '</td><td>' + esc(r.industry) + '</td>' +
        '<td>' + num(r.seal_ratio, 1) + '%</td><td>' + num(r.turnover, 1) + '%</td>' +
        '<td class="' + tone(r.main_net_yi) + '">' + signed(r.main_net_yi, 2) + '</td>' +
        '<td class="' + tone(r.main_net_5d_yi) + '">' + signed(r.main_net_5d_yi, 2) + '</td>' +
        '<td>' + r.tags.slice(0, 2).map(function (t) {
          return '<span class="mini-tag' + (t.indexOf('风险') >= 0 ? ' risk' : '') + '">' + esc(t) + '</span>';
        }).join('') + '</td></tr>';
    }).join('');

    $('poolCards').innerHTML = rows.map(function (r) {
      return '<div class="m-card" data-code="' + esc(r.code) + '"><div class="m-row1"><div class="nm">' +
        esc(r.name) + '<small>' + esc(r.code) + '</small><div class="sub">' + esc(r.industry) + ' · ' +
        r.boards + ' 板 · <span class="grade-tag grade-' + r.grade + '">' + r.grade + '</span></div></div>' +
        '<div class="m-score">' + num(r.score, 1) + '</div></div>' +
        '<div class="m-meta"><span>封单比 <b>' + num(r.seal_ratio, 1) + '%</b></span>' +
        '<span>换手 <b>' + num(r.turnover, 1) + '%</b></span>' +
        '<span>主力 <b class="' + tone(r.main_net_yi) + '">' + signed(r.main_net_yi, 2) + '亿</b></span>' +
        '<span>5日 <b class="' + tone(r.main_net_5d_yi) + '">' + signed(r.main_net_5d_yi, 2) + '亿</b></span></div>' +
        '<div class="m-tags">' + r.tags.slice(0, 3).map(function (t) {
          return '<span class="mini-tag">' + esc(t) + '</span>';
        }).join('') + '</div></div>';
    }).join('');

    var wsum = Object.keys(D.config.weights).reduce(function (a, k) {
      return a + Number(state.weights[k] || 0);
    }, 0);
    $('tableFoot').innerHTML = '评分 = 7 因子加权基础分 − 风险扣分（0~100）。当前权重合计 ' +
      wsum + '。' + srcNote('观察池数据为当日快照');
  }

  /* ---------------- 个股抽屉 ---------------- */
  function openDrawer(code) {
    var r = state.rows.filter(function (x) { return x.code === code; })[0];
    if (!r) return;
    state.currentCode = code;
    $('drawerTitle').innerHTML = esc(r.name) + ' <span class="stock-code">' + esc(r.code) + '</span> ' +
      '<span class="grade-tag grade-' + r.grade + '">' + r.grade + '</span>';
    $('drawerSub').textContent = r.industry + ' · ' + r.boards + ' 板 · 综合 ' + num(r.score, 1) + ' 分 · ' + r.grade_label;

    var labels = D.config.factor_labels;
    var keys = Object.keys(r.factors);
    var factorRows = keys.map(function (k) {
      return '<div class="factor-row"><span>' + esc(labels[k] || k) + '</span>' +
        '<div class="factor-track"><i style="width:' + r.factors[k] + '%"></i></div>' +
        '<b style="text-align:right">' + num(r.factors[k], 0) + '</b></div>';
    }).join('');

    var flowItems = [
      { label: '主力净额', value: r.main_net_yi, tip: '主力（大单+超大单）当日净额：' + num(r.main_net_yi, 2) + ' 亿' },
      { label: '超大单', value: r.super_net_yi, tip: '超大单当日净额：' + num(r.super_net_yi, 2) + ' 亿' },
      { label: '大单', value: r.big_net_yi, tip: '大单当日净额：' + num(r.big_net_yi, 2) + ' 亿' },
      { label: '中单', value: r.mid_net_yi, tip: '中单当日净额：' + num(r.mid_net_yi, 2) + ' 亿' },
      { label: '小单', value: r.small_net_yi, tip: '小单当日净额：' + num(r.small_net_yi, 2) + ' 亿' }
    ];
    var multiItems = [
      { label: '当日', value: r.main_net_yi, tip: '当日主力净额 ' + num(r.main_net_yi, 2) + ' 亿' },
      { label: '近 5 日', value: r.main_net_5d_yi, tip: '近 5 日主力净额 ' + num(r.main_net_5d_yi, 2) + ' 亿' },
      { label: '近 10 日', value: r.main_net_10d_yi, tip: '近 10 日主力净额 ' + num(r.main_net_10d_yi, 2) + ' 亿' }
    ];

    var histHtml = '';
    if (r.flow_detail_available && r.flow_history && r.flow_history.length) {
      var hh = r.flow_history.map(function (h) {
        return { label: String(h.date).slice(5), value: num((h.main_net || 0) / 1e8, 2),
                 tip: h.date + ' 主力净额 ' + num((h.main_net || 0) / 1e8, 2) + ' 亿' };
      });
      histHtml = '<div class="d-section"><h3>逐日主力净额（亿元）</h3><div class="chart-box">' +
        svgBarH(hh, { rowH: 20, labelW: 62, padR: 56 }) + '</div>' +
        '<p class="src-note">来源：东方财富个股资金流日线；逐日明细接口偶发限流，缺失时不影响上面的多周期分析。</p></div>';
    }

    var cells = [
      ['收盘价', num(r.price, 2) + ' 元'], ['涨幅', signed(r.pct, 2, '%')], ['连板', r.boards + ' 板'],
      ['封单额', num(r.seal_amount_yi, 2) + ' 亿'], ['封单比', num(r.seal_ratio, 2) + '%'],
      ['首封时间', r.first_seal], ['换手率', num(r.turnover, 2) + '%'], ['流通市值', num(r.float_mv_yi, 1) + ' 亿'],
      ['成交额', num(r.amount_yi, 2) + ' 亿'], ['板块涨停', r.sector_count + ' 家'],
      ['炸板次数', r.break_count + ' 次'], ['板块最高板', r.sector_max_board + ' 板']
    ];

    $('drawerBody').innerHTML =
      '<div class="d-section"><h3>关键数据</h3><div class="d-grid">' + cells.map(function (c) {
        return '<div class="d-cell"><div class="l">' + c[0] + '</div><div class="v">' + esc(c[1]) + '</div></div>';
      }).join('') + '</div>' + srcNote() + '</div>' +

      '<div class="d-section"><h3>七因子评分雷达</h3><div class="chart-box">' +
      svgRadar(keys.map(function (k) { return r.factors[k]; }), keys.map(function (k) { return labels[k] || k; })) +
      '</div><div style="margin-top:10px">' + factorRows + '</div>' +
      '<p class="src-note">基础分 ' + num(r.base_score, 1) + ' 分，风险扣分 ' + r.penalty_total +
      ' 分，最终 ' + num(r.score, 1) + ' 分。权重可在左侧/筛选面板中实时调整。</p></div>' +

      '<div class="d-section"><h3>主力资金结构（当日，亿元）</h3><div class="chart-box">' +
      svgBarH(flowItems, { rowH: 26, labelW: 76, padR: 66 }) + '</div>' +
      '<div class="legend"><span><i style="background:var(--up)"></i>净流入</span>' +
      '<span><i style="background:var(--down)"></i>净流出</span></div></div>' +

      '<div class="d-section"><h3>多周期资金共振</h3><div class="chart-box">' +
      svgBarH(multiItems, { rowH: 30, labelW: 76, padR: 66 }) + '</div>' +
      '<p class="src-note">' + esc(r.flow_continuity) + '。单日大额流入多为事件性脉冲，' +
      '多周期同向净流入更接近趋势性布局。</p></div>' + histHtml +

      '<div class="d-section"><h3>风险扣分明细</h3>' +
      (r.penalties.length ? r.penalties.map(function (p) {
        return '<div class="penalty-row"><span><b>' + esc(p.label) + '</b> · ' + esc(p.detail) +
               '</span><span>' + p.point + '</span></div>';
      }).join('') : '<p class="sub">无风险扣分项。</p>') + '</div>' +

      '<div class="d-section"><h3>次日观察要点（条件式，非买卖指令）</h3><div class="plan-box">' +
      '<b>竞价：</b>' + esc(r.plan.auction) + '<br><b>分时：</b>' + esc(r.plan.intraday) +
      '<br><b>失效条件：</b>' + esc(r.plan.risk) + '<br><b>仓位参考：</b>' + esc(r.plan.position) +
      '（' + esc(r.plan.board_type) + ' 标的）<br><b>前提条件：</b><ul class="d-list">' +
      r.plan.conditions.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul></div>' +
      '<p class="src-note">标签：' + (r.tags.length ? esc(r.tags.join(' / ')) : '无') + '｜' + esc(r.reasons.join('；')) + '</p></div>' +

      '<div class="d-section"><h3>数据说明</h3><p class="src-note">' + esc(D.meta.data_caveat) +
      '<br>' + esc(D.meta.disclaimer) + '</p></div>';

    $('drawer').classList.remove('hidden');
    $('mask').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    $('drawer').classList.add('hidden');
    $('mask').classList.add('hidden');
    document.body.style.overflow = '';
  }

  /* ---------------- 资金 Tab ---------------- */
  function renderFlowAlert() {
    var sh = D.meta.source_health || {};
    var qg = (sh.groups && sh.groups.quotes) || {};
    var fund = qg.fund_source || (D.meta.quality === 'full' ? 'eastmoney' : 'none');
    var msgs = [];
    if (fund === 'none') {
      msgs.push('本期全部资金接口不可用，主力资金拆解为空，资金因子按中性 50 分计，下方图表无数据。');
    } else if (fund === 'sina') {
      msgs.push('资金拆解已切换到新浪「主动买卖单」口径，与东方财富「大单+超大单」口径不等价：跨日分数不可直接比较，且该源不提供 5 日/10 日多周期。');
    } else if (fund === 'mixed') {
      msgs.push('部分个股资金来自新浪备用源，与其余个股口径不同，横向与跨日比较需谨慎。');
    }
    if (D.meta.degraded && fund !== 'none') {
      msgs.push('本期已启用备用数据源，封板质量或板块字段可能缺失，评分与历史快照不完全可比。');
    }
    var el = $('flowAlert');
    if (!msgs.length) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="plan-box" style="border-left:4px solid var(--up);margin:0 0 12px">' +
      msgs.map(function (t) {
        return '<div style="font-size:12.5px;line-height:1.7;color:var(--text-2)">⚠ ' + esc(t) + '</div>';
      }).join('') + '</div>';
  }

  function renderFlow() {
    renderFlowAlert();
    var noFund = !D.flow_leaders.length;
    var emptyHtml = '<div class="plan-box" style="border-left:4px solid var(--up)">' +
      '本期未取到主力资金拆解，资金流排行与个股资金图表为空。' +
      '系统已按多源容灾链自动降级，评分中的资金因子按中性 50 分计；' +
      '可在「策略说明 → 数据源与容灾」查看每个接口的实测状态。</div>' + srcNote();
    var top = D.flow_leaders.slice(0, 15).map(function (f) {
      return { label: f.name, value: f.main_net_yi,
               tip: f.name + '（' + f.code + '）当日主力净额 ' + num(f.main_net_yi, 2) + ' 亿，评分 ' + f.score,
               text: signed(f.main_net_yi, 2) };
    });
    $('flowChart').innerHTML = noFund ? emptyHtml :
      ('<div class="chart-box">' + svgBarH(top, { rowH: 27, labelW: 96, padR: 68 }) + '</div>' +
      '<div class="legend"><span><i style="background:var(--up)"></i>主力净流入</span>' +
      '<span><i style="background:var(--down)"></i>主力净流出</span><span>单位：亿元</span></div>' + srcNote());

    $('flowTable').innerHTML = noFund ? emptyHtml : ('<div class="scroll-x"><table class="simple-table"><thead><tr>' +
      '<th>标的</th><th>行业</th><th>评分</th><th>当日主力(亿)</th><th>主力占比</th>' +
      '<th>5日(亿)</th><th>10日(亿)</th><th>超大单(亿)</th></tr></thead><tbody>' +
      D.flow_leaders.map(function (f) {
        return '<tr><td>' + esc(f.name) + ' <span class="stock-code">' + esc(f.code) + '</span></td><td>' +
          esc(f.industry) + '</td><td>' + num(f.score, 1) + '</td><td class="' + tone(f.main_net_yi) + '">' +
          signed(f.main_net_yi, 2) + '</td><td>' + num(f.main_pct, 1) + '%</td><td class="' + tone(f.main_net_5d_yi) + '">' +
          signed(f.main_net_5d_yi, 2) + '</td><td class="' + tone(f.main_net_10d_yi) + '">' +
          signed(f.main_net_10d_yi, 2) + '</td><td class="' + tone(f.super_net_yi) + '">' +
          signed(f.super_net_yi, 2) + '</td></tr>';
      }).join('') + '</tbody></table></div>' + srcNote());

    var structGroups = D.candidates.slice(0, 8).map(function (c) {
      return { label: c.name.slice(0, 4), values: [c.super_net_yi, c.big_net_yi, c.mid_net_yi, c.small_net_yi] };
    });
    var anyValue = function (groups) {
      return groups.some(function (g) {
        return g.values.some(function (v) { return v !== null && v !== undefined; });
      });
    };
    var noDataBox = '<div class="plan-box">本期无可用资金拆解数据，图表留空（不以 0 冒充真实净额）。</div>' + srcNote();
    $('structureChart').innerHTML = anyValue(structGroups) ?
      ('<div class="chart-box">' + svgGroupedBars(structGroups, [
        { name: '超大单', color: UP }, { name: '大单', color: '#f08b5b' },
        { name: '中单', color: ACC }, { name: '小单', color: '#8b95a5' }
      ], { unit: ' 亿', height: 300 }) + '</div>' + srcNote()) : noDataBox;

    var multiGroups = D.candidates.slice(0, 8).map(function (c) {
      return { label: c.name.slice(0, 4), values: [c.main_net_yi, c.main_net_5d_yi, c.main_net_10d_yi] };
    });
    $('multiChart').innerHTML = anyValue(multiGroups) ?
      ('<div class="chart-box">' + svgGroupedBars(multiGroups, [
        { name: '当日', color: UP }, { name: '5日', color: '#f0a35b' }, { name: '10日', color: ACC }
      ], { unit: ' 亿', height: 300 }) + '</div>' + srcNote()) : noDataBox;

    $('flowNotes').innerHTML = [
      ['不要孤立看单日', '单日大额净流入常是事件性脉冲；需看 5 日 / 10 日是否同向，才接近趋势性布局。'],
      ['主力 = 大单 + 超大单', '这是按成交单笔金额推断的统计量，不是交易所披露的席位或机构真实资金，参考意义有限。'],
      ['四象限拆解', '超大单持续流入 + 小单净流出，通常代表大资金承接散户抛压；反之需警惕拉高派发。'],
      ['资金与价格背离', '流入但股价不涨、或流出但股价涨停，都要追问哪边更可信，不能只看单一指标。'],
      ['集中度', '资金高度抱团少数权重股代表共识强化；分散流入才代表整体风险偏好上升。'],
      ['与接力策略的关系', '资金因子权重 ' + D.config.weights.fund + '%，但单独高净流入不构成入选理由，需与封板强度、连板高度共同验证。']
    ].map(function (n) { return '<div class="note-item"><b>' + n[0] + '：</b>' + n[1] + '</div>'; }).join('');
  }

  /* ---------------- 板块 Tab ---------------- */
  function renderSector() {
    var top = D.sectors.slice(0, 12).map(function (s) {
      return { label: s.industry, value: s.count, color: ACC,
               tip: s.industry + '：涨停 ' + s.count + ' 家，最高 ' + s.max_board + ' 板，领涨 ' + s.leader,
               text: s.count + ' 家' };
    });
    $('sectorChart').innerHTML = '<div class="chart-box">' + svgBarH(top, { rowH: 27, labelW: 100, padR: 62 }) +
      '</div>' + srcNote('按涨停家数排序');

    var ladder = D.sentiment.ladder || {};
    var order = ['1板', '2板', '3板', '4板+'];
    var groups = order.map(function (k) { return { label: k, values: [ladder[k] || 0] }; });
    $('ladderChart').innerHTML = '<div class="chart-box">' + svgGroupedBars(groups, [
      { name: '家数', color: UP }
    ], { height: 270 }) + '</div><p class="src-note">' +
      (D.sentiment.ladder_gap ? '⚠ 当前连板梯队存在断层，是情绪退潮的警示信号。' :
        '梯队相对完整，高位与低位之间存在承接。') + '</p>' + srcNote();

    $('sectorTable').innerHTML = '<div class="scroll-x"><table class="simple-table"><thead><tr>' +
      '<th>行业板块</th><th>涨停家数</th><th>板块最高板</th><th>板块主力净额(亿)</th><th>领涨股</th></tr></thead><tbody>' +
      D.sectors.map(function (s) {
        return '<tr><td>' + esc(s.industry) + '</td><td>' + s.count + '</td><td>' + s.max_board + ' 板</td>' +
          '<td class="' + tone(s.main_net_yi) + '">' + signed(s.main_net_yi, 2) + '</td><td>' +
          esc(s.leader) + ' <span class="stock-code">' + esc(s.leader_code) + '</span></td></tr>';
      }).join('') + '</tbody></table></div>' + srcNote('板块主力净额为板块内涨停股当日主力净额合计');
  }

  /* ---------------- 复盘 Tab ---------------- */
  function renderReview() {
    var rv = D.review || {};
    var html = '<div class="section-head"><div><h2>策略跟踪复盘</h2><p class="sub">' +
      '用今日真实行情回看上一交易日观察池，检验评分分档是否有效</p></div></div>';
    if (rv.available) {
      var o = rv.overall;
      html += '<div class="kpi-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">' +
        [['跟踪样本', o.count + ' 只', ''], ['次日平均涨跌', signed(o.avg_pct, 2, '%'), tone(o.avg_pct)],
         ['上涨胜率', num(o.win_rate, 1) + '%', o.win_rate >= 50 ? 'pos' : 'neg'],
         ['晋级率', num(o.promote_rate, 1) + '%', '']].map(function (k) {
          return '<div class="kpi"><div class="k-label">' + k[0] + '</div><div class="k-value ' + k[2] +
                 '">' + k[1] + '</div></div>';
        }).join('') + '</div>';
      var gkeys = Object.keys(rv.by_grade).filter(function (g) { return rv.by_grade[g].count > 0; });
      html += '<h2 style="margin:18px 0 6px">按评分区间</h2>' +
        '<div class="chart-box">' + svgGroupedBars(gkeys.map(function (g) {
          return { label: g + ' 档', values: [rv.by_grade[g].avg_pct || 0, rv.by_grade[g].win_rate || 0] };
        }), [{ name: '平均涨跌%', color: UP }, { name: '胜率%', color: ACC }], { height: 260 }) + '</div>';
      html += '<div class="scroll-x"><table class="simple-table"><thead><tr><th>分档</th><th>样本</th>' +
        '<th>平均涨跌</th><th>胜率</th><th>晋级率</th><th>最大</th><th>最小</th></tr></thead><tbody>' +
        gkeys.map(function (g) {
          var s = rv.by_grade[g];
          return '<tr><td>' + g + ' 档</td><td>' + s.count + '</td><td class="' + tone(s.avg_pct) + '">' +
            signed(s.avg_pct, 2, '%') + '</td><td>' + num(s.win_rate, 1) + '%</td><td>' +
            num(s.promote_rate, 1) + '%</td><td class="pos">' + signed(s.max_pct, 2, '%') +
            '</td><td class="neg">' + signed(s.min_pct, 2, '%') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      html += '<h2 style="margin:18px 0 6px">个股明细</h2><div class="scroll-x"><table class="simple-table">' +
        '<thead><tr><th>标的</th><th>原评分</th><th>分档</th><th>连板</th><th>次日涨跌</th><th>是否再涨停</th></tr></thead><tbody>' +
        rv.rows.map(function (r) {
          return '<tr><td>' + esc(r.name) + ' <span class="stock-code">' + esc(r.code) + '</span></td><td>' +
            num(r.score, 1) + '</td><td>' + esc(r.grade) + '</td><td>' + r.boards + '</td><td class="' +
            tone(r.next_pct) + '">' + signed(r.next_pct, 2, '%') + '</td><td>' +
            (r.promoted ? '<span class="pos">是</span>' : '否') + '</td></tr>';
        }).join('') + '</tbody></table></div>';
      html += '<div class="plan-box" style="margin-top:14px"><b>口径提醒：</b>' + esc(rv.caveat) +
        (rv.is_intraday ? '<br><b>当前为盘中口径</b>，收盘后运行会更新为定稿数据。' : '') + '</div>';
      html += srcNote('复盘源快照 ' + esc(rv.source_snapshot) + ' → ' + esc(rv.next_day));
    } else {
      html += '<div class="plan-box">📌 ' + esc(rv.reason || '暂无复盘数据') +
        '<br><br>每个交易日收盘后运行时，系统会把当日观察池保存为快照；下一交易日运行时自动用真实行情计算' +
        '「次日平均涨跌 / 胜率 / 晋级率」，并按评分区间与连板高度分组，用于检验权重是否稳健。' +
        '<br><br><b>重要：</b>这是模拟跟踪，不等于可实现收益。涨停次日常见一字板或大幅高开，' +
        '实际难以按前收盘价成交，且未计交易成本与滑点。</div>' + srcNote();
    }
    $('reviewRoot').innerHTML = html;

    var days = (D.history_days || []).slice();
    $('historyChart').innerHTML = days.length ? '<div class="chart-box">' + svgHistory(days) + '</div>' :
      '<div class="empty">暂无历史快照，运行数个交易日后自动生成趋势图。</div>';
    $('historyTable').innerHTML = days.length ? '<div class="scroll-x"><table class="simple-table"><thead><tr>' +
      '<th>日期</th><th>涨停</th><th>炸板</th><th>炸板率</th><th>最高板</th><th>情绪</th>' +
      '<th>最高分</th><th>A档数</th></tr></thead><tbody>' + days.slice().reverse().map(function (d) {
        return '<tr><td>' + esc(d.date) + '</td><td>' + num(d.limit_up, 0) + '</td><td>' + num(d.broken, 0) +
          '</td><td>' + num(d.break_rate, 1) + '%</td><td>' + num(d.max_board, 0) + '</td><td>' +
          esc(d.sentiment) + '</td><td>' + num(d.top_score, 1) + '</td><td>' + num(d.a_count, 0) + '</td></tr>';
      }).join('') + '</tbody></table></div>' + srcNote('历史数据来自本仓库每日提交的快照') : '';
  }

  /* ---------------- 策略说明 Tab ---------------- */
  /* ---------------- 数据源与容灾 ---------------- */
  function sourceHealthHtml() {
    var m = D.meta, sh = m.source_health || {};
    var qMap = { full: '完整（主源）', partial: '部分（备用源）', minimal: '量价（备用源）',
                 none: '失效', unknown: '未知' };
    var qg = (sh.groups && sh.groups.quotes) || {};
    var head = '<h2 style="margin-top:18px">数据源与容灾</h2>' +
      '<div class="plan-box" style="margin-bottom:12px"><b>本期质量：' +
      esc(qMap[m.quality] || m.quality || '未知') + '</b>　·　检查时点 ' +
      esc(sh.checked_at || m.as_of) + '　·　失败尝试 ' + (sh.failed_count || 0) +
      ' 次　·　资金口径 ' + esc(qg.fund_source || '--') +
      (qg.fund_comparable === false ? '（与历史不可直接比较）' : '') + '</div>';
    if (!sh.groups) {
      return head + '<div class="plan-box">本页为历史 / 演示快照，无当期数据源健康记录。' +
        '运行 <code>python src/run_daily.py --no-push</code> 后会生成。</div>';
    }
    var qn = { full: '完整', partial: '部分', minimal: '量价', none: '失效' };
    var rows = Object.keys(sh.groups).map(function (k) {
      var g = sh.groups[k] || {};
      var count = g.count !== undefined ? g.count :
                  (g.coverage || ((g.available || 0) + '/' + (g.attempted || 0)));
      return '<tr style="text-align:left"><td><b>' + esc(k) + '</b></td><td>' +
        esc(g.label || g.provider || '--') + '</td><td>' + esc(qn[g.quality] || '--') +
        '</td><td>' + esc(String(count)) + '</td><td style="text-align:left;white-space:normal;min-width:200px">' +
        esc(g.endpoint || g.fund_source || '--') + '</td></tr>';
    }).join('');
    var attempts = (sh.attempts || []).slice(0, 14).map(function (a) {
      return '<tr style="text-align:left"><td>' + (a.ok ? '✅' : '❌') + '</td><td>' +
        esc(a.group) + '</td><td>' + esc(a.label) + '</td><td>' + a.ms +
        ' ms</td><td style="text-align:left;white-space:normal;min-width:220px">' +
        esc(a.detail) + '</td></tr>';
    }).join('');
    var notes = (sh.notes || []).map(function (n) {
      return '<div class="note-item">' + esc(n) + '</div>';
    }).join('');
    var chain = [
      ['涨停 / 炸板 / 跌停池', '东财 push2ex（https + http 多域名）→ 同花顺涨停池（含封板质量，仅涨停池）→ 新浪全市场涨跌幅榜按涨跌停价重建'],
      ['行情 + 主力资金', '东财 ulist.np（多域名）→ 东财 clist 榜单通道（同口径全字段）→ 腾讯证券 → 新浪榜单复用 / 逐票行情；资金仍缺时由新浪批量资金流补齐当日四类单'],
      ['多周期 / 逐日资金', '东财 push2his 与 82.push2his 双域名；失败则多周期按中性 50 分计，不影响主流程'],
      ['交叉校验', '主源为东财时额外比对同花顺涨停家数与成分重合度，偏差会在下方备注列出'],
      ['全部失效', '优先回退最近一次真实快照并标记「陈旧」，再回退仓库内置演示样本；两种情况都不推送飞书，绝不编造行情']
    ].map(function (n) {
      return '<div class="note-item"><b>' + n[0] + '：</b>' + esc(n[1]) + '</div>';
    }).join('');
    return head +
      '<div class="scroll-x"><table class="simple-table"><thead><tr><th>环节</th><th>实际来源</th>' +
      '<th>质量</th><th>条数 / 覆盖</th><th>接口</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (sh.cross_check && sh.cross_check.available ?
        '<div class="plan-box" style="margin-top:10px"><b>交叉校验：</b>东财 ' +
        sh.cross_check.primary_count + ' 家 / 同花顺 ' + sh.cross_check.ths_count +
        ' 家，成分重合 ' + sh.cross_check.overlap_rate + '%。' +
        esc(sh.cross_check.note || '') + '</div>' : '') +
      (notes ? '<h3 style="margin-top:16px;font-size:14px">本期口径提示</h3><div class="notes">' + notes + '</div>' : '') +
      '<h3 style="margin-top:16px;font-size:14px">容灾链与降级顺序</h3><div class="notes">' + chain + '</div>' +
      (attempts ? '<h3 style="margin-top:16px;font-size:14px">本次取数尝试记录</h3>' +
        '<div class="scroll-x"><table class="simple-table"><thead><tr><th>结果</th><th>环节</th>' +
        '<th>数据源</th><th>耗时</th><th>摘要 / 错误</th></tr></thead><tbody>' + attempts +
        '</tbody></table></div>' : '') +
      '<div class="plan-box" style="margin-top:12px"><b>自助排查：</b>本地运行 ' +
      '<code>python src/check_sources.py</code> 可逐项探测全部接口；GitHub Actions 页可手动运行「数据源健康自检」。' +
      '各源开关在 <code>config.json → data_sources</code>。</div>';
  }

  function renderAbout() {
    var labels = D.config.factor_labels, w = D.config.weights;
    var desc = {
      seal: '封单额/流通市值 50% + 首封时间 28% + 炸板次数 22%。封单越厚、封板越早、开板越少，说明抛压被有效承接。',
      board: '1~2 板赔率优于 4 板以上。高位龙头追涨的赔率最差，因此 2 板给满分、4 板以上快速衰减并额外扣分。',
      fund: '当日主力净额 45% + 超大单强度 30% + 5/10 日连续性 25%。刻意避免只用单日数据判断资金性质。',
      volume: '换手 8%~18% 为观察区；过低说明承接不足，超过 35% 说明分歧过大。',
      sector: '同行业涨停家数 60% + 板块最高板 40%。主流题材的续航明显强于孤立脉冲与跟风噪音。',
      liquidity: '流通市值 30~200 亿为舒适区，同时要求成交额充足，避开流动性不足导致买不进 / 卖不出的标的。',
      momentum: '近期涨停次数反映股性活跃度，过热后回落，避免把已经充分演绎的标的当成新机会。'
    };
    $('aboutRoot').innerHTML =
      '<div class="section-head"><div><h2>' + esc(D.meta.strategy) + '</h2>' +
      '<p class="sub">版本 ' + esc(D.meta.version) + ' · 全部参数集中在仓库根目录 config.json，可自行修改后重跑</p></div></div>' +
      '<div class="plan-box" style="margin-bottom:16px"><b>策略定位：</b>这不是「预测明天哪只会涨停」，' +
      '而是把当日所有涨停股按可解释的多因子排成观察池，配合资金流向与板块结构，给出次日需要验证的条件与失效信号。' +
      '输出的是观察顺序，不是收益承诺。</div>' +
      '<h2>七因子与权重</h2><div class="scroll-x"><table class="simple-table"><thead><tr>' +
      '<th>因子</th><th>权重</th><th>计算逻辑与依据</th></tr></thead><tbody>' +
      Object.keys(w).map(function (k) {
        return '<tr style="text-align:left"><td><b>' + esc(labels[k] || k) + '</b></td><td>' + w[k] +
          '%</td><td style="text-align:left;white-space:normal;min-width:280px">' + esc(desc[k] || '') + '</td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<h2 style="margin-top:18px">风险扣分与剔除规则</h2><div class="notes">' + [
        ['剔除', 'ST / *ST / 退市整理期、北交所与三板（涨跌幅机制不同）、成交额低于 5000 万'],
        ['高位连板', '4 板及以上扣 10 分，并标注「高位风险」'],
        ['反复炸板', '日内炸板 ≥3 次扣 8 分'],
        ['换手过热', '换手 >35% 扣 8 分'],
        ['主力净流出', '当日主力净额为负扣 12 分'],
        ['封单偏薄', '封单占流通市值 <0.3% 扣 6 分'],
        ['尾盘偷袭', '14:30 后才首次封板扣 6 分'],
        ['20cm / 30cm', '波动与回撤大于主板，额外扣 4 分']
      ].map(function (n) { return '<div class="note-item"><b>' + n[0] + '：</b>' + n[1] + '</div>'; }).join('') + '</div>' +
      '<h2 style="margin-top:18px">自动化链路</h2><div class="notes">' + [
        ['每日运行', 'GitHub Actions 每交易日北京时间 18:53（收盘定稿）运行一次，自动多源采集、评分、生成快照并推送；节假日通过接口返回日期自动跳过推送。'],
        ['飞书推送', '交互卡片含情绪概览、Top 候选、主力资金聚焦与按钮：打开看板 / 资金明细 / 数据源状态 / 策略说明 / 标记已阅。降级时卡片会标注口径，支持加签。'],
        ['交互看板', '本页由 GitHub Pages 托管，手机与电脑自适应；可筛选、排序、拖动因子权重实时重排、下钻个股资金与评分。'],
        ['复盘闭环', '每日快照提交进仓库，下一交易日自动计算观察池的次日涨跌、胜率与晋级率，用于检验参数稳健性。'],
        ['零第三方依赖', 'Python 后端只用标准库，前端只用原生 JS + SVG，Actions 无需 pip install，本地双击 HTML 也能看数据。'],
        ['配置位置', '根目录 config.json（权重/阈值）、GitHub Secrets（FEISHU_WEBHOOK / FEISHU_SECRET / PAGES_URL）。']
      ].map(function (n) { return '<div class="note-item"><b>' + n[0] + '：</b>' + n[1] + '</div>'; }).join('') + '</div>' +
      '<h2 style="margin-top:18px">部署与推送配置</h2><div class="notes">' + [
        ['① 上传到 GitHub', '把整个仓库推到新仓库；.github/workflows/daily.yml 会自动注册每交易日 18:53（北京时间）的定时任务。'],
        ['② 开启 Pages', '仓库 Settings → Pages → Build and deployment → Source 选「GitHub Actions」；部署完成后得到 https://&lt;用户名&gt;.github.io/&lt;仓库名&gt;/。'],
        ['③ 配置飞书机器人', '飞书群 → 设置 → 群机器人 → 添加自定义机器人；复制 Webhook 地址，建议开启「加签」并复制密钥。'],
        ['④ 配置 Secrets', '仓库 Settings → Secrets and variables → Actions：FEISHU_WEBHOOK（必填）、FEISHU_SECRET（加签必填）、PAGES_URL（可留空，Actions 会自动推导）。'],
        ['⑤ 首次运行', 'Actions 页签 → 「每日涨停接力策略」→ Run workflow（mode 选 close）→ 检查飞书是否收到交互卡片、Pages 是否可访问。'],
        ['⑥ 本地预览', 'python src/run_daily.py --no-push 生成数据，再 python scripts/serve.py，浏览器打开 http://127.0.0.1:8000/；也可直接双击 index.html。']
      ].map(function (n) { return '<div class="note-item"><b>' + n[0] + '：</b>' + n[1] + '</div>'; }).join('') + '</div>' +
      sourceHealthHtml() +
      '<h2 style="margin-top:18px">已知局限</h2><div class="plan-box">' +
      '① 数据源为公开行情接口，定时任务在收盘后 18:53 生成当日定稿；盘中手动运行得到的是实时快照，尾盘炸板会导致结果变化；' +
      '② 主力资金是按成交单笔金额推断的统计量，不是真实席位资金；' +
      '③ 题材分类采用行情接口的行业字段，不覆盖概念题材的叠加归属；' +
      '④ 评分为专家规则加权，未做样本外参数寻优，历史复盘样本会随运行天数逐步积累；' +
      '⑤ 涨停次日常见一字板 / 大幅高开，模拟溢价不等于可实现收益，未计成本与滑点。</div>' +
      '<div class="plan-box" style="margin-top:14px;border-left:4px solid var(--up)"><b>' +
      esc(D.meta.disclaimer) + '</b></div>' + srcNote();
  }

  /* ---------------- 日期切换 ---------------- */
  function renderDates() {
    var days = (HIST.days || []).slice().sort(function (a, b) { return b.date.localeCompare(a.date); });
    var current = D.meta.date;
    if (!days.some(function (d) { return d.date === current; })) {
      days.unshift({ date: current });
    }
    $('dateSelect').innerHTML = days.map(function (d) {
      return '<option value="' + esc(d.date) + '"' + (d.date === current ? ' selected' : '') + '>' +
        esc(d.date) + '</option>';
    }).join('');
  }

  function switchDate(date) {
    if (date === D.meta.date) return;
    fetch('data/daily/' + date + '.json', { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (json) {
      D = json;
      state.weights = clone(D.config.weights);
      state.customWeights = false;
      state.rows = reRank(D.candidates, state.weights);
      renderAll();
    }).catch(function () {
      window.alert('无法载入 ' + date + ' 的快照。本地以 file:// 打开时仅能查看当前数据；请用 python scripts/serve.py 或 GitHub Pages 访问。');
      renderDates();
    });
  }

  /* ---------------- 事件 ---------------- */
  var TAB_NAMES = ['pool', 'flow', 'sector', 'review', 'about'];

  // 支持通过 #flow / #sector 等锚点直达对应页签（飞书卡片按钮使用）
  function activateTab(name, syncHash) {
    if (TAB_NAMES.indexOf(name) < 0) name = 'pool';
    state.tab = name;
    Array.prototype.forEach.call(document.querySelectorAll('.tab'), function (x) {
      x.classList.toggle('active', x.dataset.tab === name);
    });
    Array.prototype.forEach.call(document.querySelectorAll('.tab-panel'), function (p) {
      p.classList.toggle('active', p.id === 'panel-' + name);
    });
    if (syncHash && window.history && history.replaceState) {
      history.replaceState(null, '', '#' + name);
    }
  }

  function bind() {
    $('tabs').addEventListener('click', function (e) {
      var b = e.target.closest('.tab');
      if (!b) return;
      activateTab(b.dataset.tab, true);
    });

    window.addEventListener('hashchange', function () {
      activateTab((location.hash || '').replace(/^#/, ''), false);
    });

    $('searchInput').addEventListener('input', function (e) { state.filters.q = e.target.value; renderPool(); });
    $('minScore').addEventListener('input', function (e) {
      state.filters.minScore = Number(e.target.value); renderPool();
    });
    $('gradeChips').addEventListener('click', function (e) {
      var b = e.target.closest('.chip'); if (!b) return;
      state.filters.grade = b.dataset.grade;
      Array.prototype.forEach.call(this.querySelectorAll('.chip'), function (x) {
        x.classList.toggle('active', x === b);
      });
      renderPool();
    });
    $('boardFilter').addEventListener('change', function (e) { state.filters.board = e.target.value; renderPool(); });
    $('industryFilter').addEventListener('change', function (e) { state.filters.industry = e.target.value; renderPool(); });
    $('sortSelect').addEventListener('change', function (e) { state.filters.sort = e.target.value; renderPool(); });

    $('weightSliders').addEventListener('input', function (e) {
      var k = e.target.dataset.weight; if (!k) return;
      state.weights[k] = Number(e.target.value);
      state.customWeights = true;
      var row = e.target.closest('.weight-row');
      row.querySelector('b').textContent = state.weights[k];
      state.rows = reRank(D.candidates, state.weights);
      renderPool();
    });
    $('resetWeights').addEventListener('click', function () {
      state.weights = clone(D.config.weights);
      state.customWeights = false;
      state.rows = reRank(D.candidates, state.weights);
      renderWeights(); renderPool();
    });
    $('resetAll').addEventListener('click', function () {
      state.filters = { q: '', grade: 'ALL', board: 'ALL', industry: 'ALL', minScore: 55, sort: 'score' };
      state.weights = clone(D.config.weights);
      state.customWeights = false;
      $('searchInput').value = ''; $('minScore').value = 55;
      $('boardFilter').value = 'ALL'; $('industryFilter').value = 'ALL'; $('sortSelect').value = 'score';
      Array.prototype.forEach.call($('gradeChips').querySelectorAll('.chip'), function (x) {
        x.classList.toggle('active', x.dataset.grade === 'ALL');
      });
      state.rows = reRank(D.candidates, state.weights);
      renderWeights(); renderAll();
    });

    function openFromTable(e) {
      var el = e.target.closest('[data-code]');
      if (el) openDrawer(el.dataset.code);
    }
    $('poolBody').addEventListener('click', openFromTable);
    $('poolCards').addEventListener('click', openFromTable);
    $('drawerClose').addEventListener('click', closeDrawer);
    $('mask').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDrawer(); });

    $('flowSwitch').addEventListener('click', function (e) {
      var b = e.target.closest('.switch-btn'); if (!b) return;
      state.flowView = b.dataset.view;
      Array.prototype.forEach.call(this.querySelectorAll('.switch-btn'), function (x) {
        x.classList.toggle('active', x === b);
      });
      $('flowChart').classList.toggle('hidden', state.flowView !== 'chart');
      $('flowTable').classList.toggle('hidden', state.flowView !== 'table');
    });

    $('themeBtn').addEventListener('click', function () {
      state.theme = state.theme === 'light' ? 'dark' : 'light';
      localStorage.setItem('relay-theme', state.theme);
      document.documentElement.setAttribute('data-theme', state.theme);
      $('themeBtn').textContent = state.theme === 'light' ? '◐' : '☀';
    });
    $('refreshBtn').addEventListener('click', function () { location.reload(); });
    $('dateSelect').addEventListener('change', function (e) { switchDate(e.target.value); });
    $('toggleFilters').addEventListener('click', function () { $('filterSide').classList.toggle('open'); });

    var tip = $('tooltip');
    document.addEventListener('mousemove', function (e) {
      var t = e.target.closest ? e.target.closest('[data-tip]') : null;
      if (!t) { tip.classList.add('hidden'); return; }
      tip.textContent = t.getAttribute('data-tip');
      tip.classList.remove('hidden');
      var x = Math.min(e.clientX + 12, window.innerWidth - tip.offsetWidth - 10);
      var y = Math.max(8, e.clientY - tip.offsetHeight - 10);
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    });
  }

  function renderAll() {
    renderHeader();
    renderDates();
    renderWeights();
    renderIndustries();
    renderPool();
    renderFlow();
    renderSector();
    renderReview();
    renderAbout();
  }

  function init() {
    if (!D) {
      document.querySelector('.container').innerHTML =
        '<div class="card section-card"><h2>数据未载入</h2><p class="sub">请先运行 ' +
        '<code>python src/run_daily.py --no-push</code> 生成 docs/data/latest.js，' +
        '或执行 <code>python scripts/serve.py</code> 后访问 http://127.0.0.1:8000/。</p></div>';
      return;
    }
    state.weights = clone(D.config.weights);
    state.grades = D.config.grades || state.grades;
    state.rows = reRank(D.candidates, state.weights);
    renderAll();
    bind();
    activateTab((location.hash || '').replace(/^#/, ''), false);
  }

  init();
})();
