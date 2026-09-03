/* AI Teacher — Whiteboard chalk renderer
 * Renders the 9 code-drawn primitives on a canvas with an authentic chalkboard aesthetic:
 *   write_text, draw_equation (KaTeX), plot_graph, draw_diagram,
 *   draw_timeline, write_code, draw_map, draw_flowchart, show_table, draw_concept_card
 * Board units: x,y in 0..100, scaled to canvas size.
 */
'use strict';

const Whiteboard = (() => {

  const COLORS = {
    white: '#f8fafc',
    yellow: '#fde047',
    blue: '#38bdf8',
    pink: '#f472b6',
    green: '#4ade80',
    orange: '#fb923c',
  };
  const INK = '#f8fafc'; // Default chalk on dark blackboard
  const INK_COLORS = {
    white: '#f8fafc',
    yellow: '#fde047',
    blue: '#38bdf8',
    pink: '#f472b6',
    green: '#4ade80',
    orange: '#fb923c',
  };

  let canvas, ctx, W = 1000, H = 620, dpr = 1;

  function init(canvasEl) {
    canvas = canvasEl;
    resize();
    window.addEventListener('resize', () => { resize(); redraw(); });
    clear();
  }

  function resize() {
    if (!canvas || !canvas.parentElement) return;
    const rect = canvas.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    W = Math.max(320, rect.width);
    H = Math.max(240, rect.height);
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // state: list of draw operations that can be replayed on resize
  let ops = [];

  function clear() {
    ops = [];
    // Clear DOM overlay elements (e.g. KaTeX equation cards)
    const overlay = document.getElementById('board-overlay');
    if (overlay) overlay.innerHTML = '';

    if (!ctx) return;
    // Authentic deep slate forest-green chalkboard gradient
    const bgGrad = ctx.createLinearGradient(0, 0, W, H);
    bgGrad.addColorStop(0, '#15241b');
    bgGrad.addColorStop(0.5, '#18291e');
    bgGrad.addColorStop(1, '#131e17');
    ctx.fillStyle = bgGrad;
    ctx.fillRect(0, 0, W, H);

    // Realistic chalk dust smudges & eraser wipe traces
    ctx.save();
    ctx.globalAlpha = 0.035;
    ctx.fillStyle = '#ffffff';
    for (let i = 0; i < 18; i++) {
      const cx = (Math.sin(i * 127) * 0.5 + 0.5) * W;
      const cy = (Math.cos(i * 459) * 0.5 + 0.5) * H;
      const r = 40 + (i % 6) * 35;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  function redraw() {
    const replay = ops;
    ops = [];
    clear();
    for (const op of replay) _exec(op, false);
  }

  // ---- helpers ---------------------------------------------------------

  const ux = (x) => (x / 100) * W;
  const uy = (y) => (y / 100) * H;
  const uw = (w) => (w / 100) * W;
  const uh = (h) => (h / 100) * H;

  function inkColor(chalk) {
    return INK_COLORS[chalk] || INK;
  }

  function chalkLine(pathFn, color, width = 2.5, dash = false) {
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    // Realistic luminous chalk glow
    ctx.shadowColor = color;
    ctx.shadowBlur = 4;
    if (dash) ctx.setLineDash([8, 6]);
    ctx.beginPath();
    pathFn();
    ctx.stroke();
    ctx.restore();
  }

  function roundRect(context, x, y, width, height, radius = 8, fill = false, stroke = true) {
    if (width < 2 * radius) radius = width / 2;
    if (height < 2 * radius) radius = height / 2;
    context.beginPath();
    context.moveTo(x + radius, y);
    context.arcTo(x + width, y, x + width, y + height, radius);
    context.arcTo(x + width, y + height, x, y + height, radius);
    context.arcTo(x, y + height, x, y, radius);
    context.arcTo(x, y, x + width, y, radius);
    context.closePath();
    if (fill) context.fill();
    if (stroke) context.stroke();
  }

  function wrapText(text, x, y, maxW, lh, color, size, bold = false) {
    ctx.save();
    ctx.fillStyle = color;
    ctx.font = `${bold ? '700' : '500'} ${size}px 'Segoe UI', system-ui, sans-serif`;
    ctx.textBaseline = 'top';
    ctx.shadowColor = color;
    ctx.shadowBlur = 3;
    const words = String(text).split(/\s+/);
    let line = '', yy = y;
    for (const w of words) {
      const test = line ? line + ' ' + w : w;
      if (ctx.measureText(test).width > maxW && line) {
        ctx.fillText(line, x, yy);
        yy += lh;
        line = w;
      } else {
        line = test;
      }
    }
    if (line) ctx.fillText(line, x, yy);
    ctx.restore();
    return yy + lh;
  }

  // ---- primitives ------------------------------------------------------

  function writeText(args) {
    const { text, title, position = 'center', chalk = 'white', append = false } = args;
    if (!append) clearAllTextKeepVisuals();
    const color = inkColor(chalk);
    let x, y;
    const zones = {
      center: [0.08, 0.16], left: [0.06, 0.45], right: [0.55, 0.45],
      top: [0.08, 0.08], bottom: [0.08, 0.72],
    };
    [x, y] = zones[position] || zones.center;
    let cx = ux(x * 100), cy = uy(y * 100);
    const maxW = W * 0.86;

    if (title) {
      ctx.save();
      ctx.fillStyle = '#fde047'; // Gold chalk title
      ctx.shadowColor = 'rgba(253, 224, 71, 0.5)';
      ctx.shadowBlur = 6;
      wrapText(title, cx, cy, maxW, 36, '#fde047', 26, true);
      ctx.restore();
      cy += 46;
    }

    const lines = String(text).split('\\n').join('\n').split('\n');
    let yy = cy;
    for (const line of lines) {
      if (/^\s*[-*•]\s+/.test(line)) {
        // Bullet with glowing chalk pip
        ctx.save();
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 4;
        ctx.beginPath();
        ctx.arc(cx + 8, yy + 14, 4.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        yy = wrapText(line.replace(/^\s*[-*•]\s+/, ''), cx + 26, yy, maxW - 26, 32, color, 21);
      } else {
        yy = wrapText(line, cx, yy, maxW, 32, color, 21);
      }
    }
    ops.push({ tool: 'write_text', args });
  }

  function clearAllTextKeepVisuals() {
    const visualOps = ops.filter(o => o.tool !== 'write_text');
    const txtOpsBefore = ops.filter(o => o.tool === 'write_text' && o.args.append === true);
    ops = [...visualOps, ...txtOpsBefore];
    redraw();
    ops = [...ops];
  }

  function drawEquation(args) {
    const { latex, label, position = 'bottom', chalk = 'yellow' } = args;
    const overlay = document.getElementById('board-overlay');
    const color = inkColor(chalk);

    if (overlay) {
      // Remove previous equation cards if position overlaps
      let card = overlay.querySelector(`.board-equation-card[data-pos="${position}"]`);
      if (!card) {
        card = document.createElement('div');
        card.className = 'board-equation-card';
        card.setAttribute('data-pos', position);
        overlay.appendChild(card);
      }

      card.style.borderColor = color;
      card.style.color = color;
      card.style.boxShadow = `0 0 18px ${color}55, inset 0 0 14px rgba(0,0,0,0.6)`;

      let posCss = '';
      if (position === 'bottom') {
        posCss = 'bottom: 24px; left: 50%; transform: translateX(-50%); max-width: 90%;';
      } else if (position === 'top') {
        posCss = 'top: 24px; left: 50%; transform: translateX(-50%); max-width: 90%;';
      } else if (position === 'left') {
        posCss = 'top: 50%; left: 30px; transform: translateY(-50%); max-width: 45%;';
      } else if (position === 'right') {
        posCss = 'top: 50%; right: 30px; transform: translateY(-50%); max-width: 45%;';
      } else { // center
        posCss = 'top: 50%; left: 50%; transform: translate(-50%, -50%); max-width: 90%;';
      }
      card.style.cssText += posCss;

      let inner = '';
      if (label) {
        inner += `<div class="board-equation-label" style="color:${color};">${label}</div>`;
      }
      const span = document.createElement('span');
      try {
        katex.render(String(latex), span, { throwOnError: false, displayMode: true });
      } catch (e) {
        span.textContent = latex;
      }
      inner += span.outerHTML;
      card.innerHTML = inner;
    }
    ops.push({ tool: 'draw_equation', args });
  }

  function maxBoardW() { return W * 0.82; }

  function plotGraph(args) {
    const { functions = [], points = [], x_range = [-5, 5], y_range,
      x_label = 'x', y_label = 'y', title, show_grid = true } = args;
    const padL = 60, padB = 46, padT = title ? 48 : 28, padR = 28;
    const gx = padL, gy = padT, gw = W - padL - padR, gh = H - padT - padB;
    let [xmin, xmax] = x_range;
    if (!isFinite(xmin) || !isFinite(xmax) || xmax <= xmin) { xmin = -5; xmax = 5; }

    let ymin = Infinity, ymax = -Infinity;
    const samples = [];
    for (const f of functions) {
      const fn = compileFn(f.fn);
      const pts = [];
      for (let i = 0; i <= 200; i++) {
        const x = xmin + (xmax - xmin) * i / 200;
        let y;
        try { y = fn(x); } catch (e) { y = NaN; }
        pts.push([x, y]);
        if (isFinite(y)) { ymin = Math.min(ymin, y); ymax = Math.max(ymax, y); }
      }
      samples.push({ pts, color: f.color || 'yellow', label: f.label });
    }
    for (const p of (points || [])) {
      ymin = Math.min(ymin, p[1]); ymax = Math.max(ymax, p[1]);
    }
    if (!isFinite(ymin)) { ymin = -5; ymax = 5; }
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const pad = (ymax - ymin) * 0.08;
    ymin -= pad; ymax += pad;
    if (y_range && isFinite(y_range[0]) && isFinite(y_range[1])) {
      [ymin, ymax] = y_range;
    }

    const X = (x) => gx + ((x - xmin) / (xmax - xmin)) * gw;
    const Y = (y) => gy + gh - ((y - ymin) / (ymax - ymin)) * gh;

    // Grid lines in faint chalk
    if (show_grid) {
      ctx.save();
      ctx.strokeStyle = 'rgba(248, 250, 252, 0.12)';
      ctx.lineWidth = 1;
      for (let i = 0; i <= 10; i++) {
        const xx = gx + (gw * i / 10);
        ctx.beginPath(); ctx.moveTo(xx, gy); ctx.lineTo(xx, gy + gh); ctx.stroke();
        const yy = gy + (gh * i / 10);
        ctx.beginPath(); ctx.moveTo(gx, yy); ctx.lineTo(gx + gw, yy); ctx.stroke();
      }
      ctx.restore();
    }

    // Axes
    chalkLine(() => {
      ctx.moveTo(gx, gy); ctx.lineTo(gx, gy + gh);
      ctx.moveTo(gx, gy + gh); ctx.lineTo(gx + gw, gy + gh);
    }, '#f8fafc', 2.8);

    // Axis labels + ticks
    ctx.save();
    ctx.fillStyle = '#cbd5e1';
    ctx.font = `600 13px 'Segoe UI', sans-serif`;
    ctx.textAlign = 'center';
    const fmt = (v) => (Math.abs(v) < 1e-9 ? '0'
      : Math.abs(v) >= 100 || Math.abs(v) < 0.01 ? v.toPrecision(2) : v.toFixed(Math.abs(v) < 10 ? 1 : 0));
    for (let i = 0; i <= 10; i++) {
      const x = xmin + (xmax - xmin) * i / 10;
      ctx.fillText(fmt(x), gx + gw * i / 10, gy + gh + 18);
    }
    ctx.textAlign = 'right';
    for (let i = 0; i <= 10; i++) {
      const y = ymin + (ymax - ymin) * i / 10;
      ctx.fillText(fmt(y), gx - 8, gy + gh - gh * i / 10 + 4);
    }
    ctx.textAlign = 'center';
    ctx.fillText(x_label, gx + gw / 2, gy + gh + 36);
    ctx.save();
    ctx.translate(20, gy + gh / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(y_label, 0, 0);
    ctx.restore();

    if (title) {
      ctx.fillStyle = '#fde047';
      ctx.font = `700 22px 'Segoe UI', sans-serif`;
      ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
      ctx.shadowBlur = 5;
      ctx.fillText(title, W / 2, padT - 18);
    }
    ctx.restore();

    // Plot curves
    for (const s of samples) {
      const color = inkColor(s.color);
      chalkLine(() => {
        let started = false;
        for (const [x, y] of s.pts) {
          if (!isFinite(y)) { started = false; continue; }
          const px = X(x), py = Y(y);
          if (!started) { ctx.moveTo(px, py); started = true; }
          else ctx.lineTo(px, py);
        }
      }, color, 3.2);
    }

    // Scatter points
    ctx.save();
    for (const [x, y] of (points || [])) {
      ctx.fillStyle = '#f472b6';
      ctx.shadowColor = '#f472b6';
      ctx.shadowBlur = 6;
      ctx.beginPath();
      ctx.arc(X(x), Y(y), 5.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // Legend
    if (samples.some(s => s.label)) {
      ctx.save();
      ctx.font = `600 14px 'Segoe UI', sans-serif`;
      let lx = gx + 14, ly = gy + 16;
      for (const s of samples) {
        if (!s.label) continue;
        chalkLine(() => {
          ctx.moveTo(lx, ly - 4); ctx.lineTo(lx + 26, ly - 4);
        }, inkColor(s.color), 3);
        ctx.fillStyle = '#f8fafc';
        ctx.textAlign = 'left';
        ctx.fillText(s.label, lx + 34, ly - 10);
        ly += 22;
      }
      ctx.restore();
    }
    ops.push({ tool: 'plot_graph', args });
  }

  function compileFn(expr) {
    const cleaned = String(expr)
      .replace(/\^/g, '**')
      .replace(/Math\./g, '')
      .replace(/(sin|cos|tan|sqrt|abs|log|exp|pow)/g, 'Math.$1');
    try {
      return new Function('x', `"use strict"; return (${cleaned});`);
    } catch (e) {
      return () => NaN;
    }
  }

  // ---- draw_diagram shape vocabulary -----------------------------------

  function drawDiagram(args) {
    const { shapes = [], title, clear_first = true } = args;
    if (clear_first) {
      ops = [];
      clear();
    }
    if (title) {
      ctx.save();
      ctx.fillStyle = '#fde047'; // Gold chalk title
      ctx.font = `700 24px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.45)';
      ctx.shadowBlur = 6;
      ctx.fillText(title, W / 2, 38);
      ctx.restore();
    }
    for (const s of shapes) drawShape(s);
    ops.push({ tool: 'draw_diagram', args });
  }

  function labelAt(x, y, text, pos, color, size = 15) {
    if (!text) return;
    ctx.save();
    ctx.fillStyle = color;
    ctx.font = `700 ${size}px 'Segoe UI', sans-serif`;
    ctx.textAlign = 'center';
    ctx.shadowColor = color;
    ctx.shadowBlur = 4;
    let yy = y - 10;
    if (pos === 'below') yy = y + 20;
    else if (pos === 'left') { ctx.textAlign = 'right'; yy = y + 4; x -= 10; }
    else if (pos === 'right') { ctx.textAlign = 'left'; yy = y + 4; x += 10; }
    ctx.fillText(text, x, yy);
    ctx.restore();
  }

  function drawShape(s) {
    const c = inkColor(s.chalk || 'white');
    const kind = s.kind || s.type || s.shape || 'rect';
    const x = ux(s.x ?? 50), y = uy(s.y ?? 50);
    const w = uw(s.w ?? 20), h = uh(s.h ?? 12);
    const x2 = s.x2 != null ? ux(s.x2) : null, y2 = s.y2 != null ? uy(s.y2) : null;
    const r = uw(s.r ?? 6);

    switch (kind) {
      case 'rect':
        chalkLine(() => {
          roundRect(ctx, x - w / 2, y - h / 2, w, h, 8, false, true);
        }, c, 2.8, s.dash);
        if (s.fill) {
          ctx.save();
          ctx.fillStyle = c + '22';
          roundRect(ctx, x - w / 2, y - h / 2, w, h, 8, true, false);
          ctx.restore();
        }
        labelAt(x, y - h / 2, s.label, s.label_pos || 'above', c);
        break;

      case 'circle':
        chalkLine(() => ctx.arc(x, y, r, 0, Math.PI * 2), c, 2.8, s.dash);
        if (s.fill) {
          ctx.save();
          ctx.fillStyle = c + '22';
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
        labelAt(x, y - r, s.label, s.label_pos || 'above', c);
        break;

      case 'ellipse':
        chalkLine(() => ctx.ellipse(x, y, w / 2, h / 2, 0, 0, Math.PI * 2), c, 2.8, s.dash);
        labelAt(x, y - h / 2, s.label, s.label_pos || 'above', c);
        break;

      case 'line':
        chalkLine(() => {
          ctx.moveTo(x, y);
          if (s.points && s.points.length >= 4) {
            for (let i = 2; i < s.points.length; i += 2) {
              ctx.lineTo(ux(s.points[i]), uy(s.points[i + 1]));
            }
          } else {
            ctx.lineTo(x2 ?? x + 50, y2 ?? y);
          }
        }, c, 2.8, s.dash);
        break;

      case 'arrow':
      case 'double_arrow': {
        const tx = x2 ?? x + 50, ty = y2 ?? y;
        chalkLine(() => { ctx.moveTo(x, y); ctx.lineTo(tx, ty); }, c, 3.2);
        arrowHead(tx, ty, x, y, c);
        if (kind === 'double_arrow') arrowHead(x, y, tx, ty, c);
        labelAt((x + tx) / 2, (y + ty) / 2, s.label, s.label_pos || 'above', c);
        break;
      }

      case 'vector': {
        let tx = x2, ty = y2;
        if (tx == null || ty == null) {
          const mag = Math.max(24, uw(s.w ?? 22));
          const rad = ((s.angle_deg ?? 0) * Math.PI) / 180;
          tx = x + mag * Math.cos(rad);
          ty = y - mag * Math.sin(rad);
        }
        chalkLine(() => { ctx.moveTo(x, y); ctx.lineTo(tx, ty); }, c, 3.6);
        arrowHead(tx, ty, x, y, c, 13);
        labelAt((x + tx) / 2, (y + ty) / 2, s.label, s.label_pos || 'above', c);
        break;
      }

      case 'arc':
        chalkLine(() => ctx.arc(x, y, r, 0, Math.PI * 1.5), c, 2.8, s.dash);
        break;

      case 'polygon': {
        const pts = s.points || [];
        chalkLine(() => {
          for (let i = 0; i + 1 < pts.length; i += 2) {
            const px = ux(pts[i]), py = uy(pts[i + 1]);
            i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
          }
          ctx.closePath();
        }, c, 2.8, s.dash);
        break;
      }

      case 'label':
        labelAt(x, y, s.label, s.label_pos || 'above', c, 18);
        break;

      case 'inclined_plane': {
        const bw = w * 1.6, bh = h;
        chalkLine(() => {
          ctx.moveTo(x - bw / 2, y + bh / 2);
          ctx.lineTo(x + bw / 2, y + bh / 2);
          ctx.lineTo(x - bw / 2, y - bh / 2);
          ctx.closePath();
        }, c, 3.2);
        labelAt(x, y, s.label, 'above', c);
        break;
      }

      // ---- circuit symbols ----
      case 'wire':
        chalkLine(() => {
          if (s.points && s.points.length >= 4) {
            ctx.moveTo(ux(s.points[0]), uy(s.points[1]));
            for (let i = 2; i < s.points.length; i += 2) {
              ctx.lineTo(ux(s.points[i]), uy(s.points[i + 1]));
            }
          } else {
            ctx.moveTo(x, y);
            ctx.lineTo(x2 ?? x + 60, y2 ?? y);
          }
        }, c, 2.8);
        break;

      case 'resistor':
        drawZigzag(x, y, x2 ?? x + 80, y2 ?? y, c);
        labelAt((x + (x2 ?? x + 80)) / 2, y, s.label, s.label_pos || 'above', c);
        break;

      case 'battery': {
        const tx = x2 ?? x + 50, ty = y2 ?? y;
        const dx = tx - x, dy = ty - y;
        const len = Math.hypot(dx, dy) || 1;
        const uxh = dx / len, uyh = dy / len;
        const pxv = -uyh, pyv = uxh;
        const long = 24, short = 14;
        chalkLine(() => {
          ctx.moveTo(x, y); ctx.lineTo(x + uxh * 10, y + uyh * 10);
          ctx.moveTo(x + uxh * 10 + pxv * long, y + uyh * 10 + pyv * long);
          ctx.lineTo(x + uxh * 10 - pxv * long, y + uyh * 10 - pyv * long);
          ctx.moveTo(x + uxh * 22 + pxv * short, y + uyh * 22 + pyv * short);
          ctx.lineTo(x + uxh * 22 - pxv * short, y + uyh * 22 - pyv * short);
          ctx.moveTo(x + uxh * 32, y + uyh * 32);
          ctx.lineTo(tx, ty);
        }, c, 3.2);
        const vl = s.voltage != null ? `${s.voltage}V` : (s.label || '');
        if (vl) labelAt((x + tx) / 2 + pxv * 32, (y + ty) / 2 + pyv * 32, vl, 'above', c);
        break;
      }

      case 'bulb': {
        chalkLine(() => ctx.arc(x, y, 15, 0, Math.PI * 2), c, 2.8);
        chalkLine(() => {
          ctx.moveTo(x - 10, y - 10); ctx.lineTo(x + 10, y + 10);
          ctx.moveTo(x + 10, y - 10); ctx.lineTo(x - 10, y + 10);
        }, c, 2.2);
        labelAt(x, y - 20, s.label, 'above', c);
        break;
      }

      case 'switch':
        chalkLine(() => { ctx.moveTo(x, y); ctx.lineTo(x + 18, y - 14); }, c, 3.2);
        chalkLine(() => { ctx.moveTo(x + 22, y); ctx.lineTo(x2 ?? x + 60, y2 ?? y); }, c, 2.8);
        chalkLine(() => { ctx.moveTo(x - 20, y); ctx.lineTo(x, y); }, c, 2.8);
        labelAt(x, y - 18, s.label, 'above', c);
        break;

      case 'ammeter': case 'voltmeter': {
        chalkLine(() => ctx.arc(x, y, 16, 0, Math.PI * 2), c, 2.8);
        ctx.save();
        ctx.fillStyle = c;
        ctx.font = `700 16px 'Segoe UI', sans-serif`;
        ctx.textAlign = 'center';
        ctx.shadowColor = c;
        ctx.shadowBlur = 4;
        ctx.fillText(kind === 'ammeter' ? 'A' : 'V', x, y + 5);
        ctx.restore();
        labelAt(x, y - 20, s.label, 'above', c);
        break;
      }

      default:
        chalkLine(() => {
          roundRect(ctx, x - w / 2, y - h / 2, w, h, 8, false, true);
        }, c, 2.5);
        labelAt(x, y - h / 2, s.label, s.label_pos || 'above', c);
    }
  }

  function drawZigzag(x, y, tx, ty, c) {
    const dx = tx - x, dy = ty - y;
    const len = Math.hypot(dx, dy) || 1;
    const uxh = dx / len, uyh = dy / len;
    const pxv = -uyh, pyv = uxh;
    const lead = (len - 44) / 2;
    chalkLine(() => {
      ctx.moveTo(x, y);
      ctx.lineTo(x + uxh * lead, y + uyh * lead);
      for (let i = 0; i < 6; i++) {
        const t = lead + (44 / 6) * (i + 0.5);
        const amp = i % 2 ? 10 : -10;
        ctx.lineTo(x + uxh * t + pxv * amp, y + uyh * t + pyv * amp);
      }
      ctx.lineTo(x + uxh * (lead + 44), y + uyh * (lead + 44));
      ctx.lineTo(tx, ty);
    }, c, 3.2);
  }

  function arrowHead(tx, ty, fx, fy, c, size = 12) {
    const a = Math.atan2(ty - fy, tx - fx);
    ctx.save();
    ctx.fillStyle = c;
    ctx.shadowColor = c;
    ctx.shadowBlur = 4;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - size * Math.cos(a - 0.45), ty - size * Math.sin(a - 0.45));
    ctx.lineTo(tx - size * Math.cos(a + 0.45), ty - size * Math.sin(a + 0.45));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // ---- timeline ----------------------------------------------------------

  function drawTimeline(args) {
    const { events = [], title, alternating = true } = args;
    ops = []; redraw();
    const bandY = H * 0.52;
    const x0 = W * 0.08, x1 = W * 0.92;
    if (title) {
      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `700 24px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
      ctx.shadowBlur = 6;
      ctx.fillText(title, W / 2, 40);
      ctx.restore();
    }
    chalkLine(() => {
      ctx.moveTo(x0, bandY); ctx.lineTo(x1, bandY);
    }, '#f8fafc', 3.5);
    arrowHead(x1, bandY, x0, bandY, '#f8fafc', 13);

    const n = events.length;
    events.forEach((ev, i) => {
      const ex = x0 + ((x1 - x0) * (n === 1 ? 0.5 : i / (n - 1)));
      const up = alternating ? i % 2 === 0 : true;
      const dir = up ? -1 : 1;
      chalkLine(() => {
        ctx.moveTo(ex, bandY); ctx.lineTo(ex, bandY + dir * 46);
      }, '#38bdf8', 2.2);

      ctx.save();
      ctx.fillStyle = '#f472b6';
      ctx.shadowColor = '#f472b6';
      ctx.shadowBlur = 6;
      ctx.beginPath(); ctx.arc(ex, bandY, 5.5, 0, Math.PI * 2); ctx.fill();
      ctx.restore();

      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `800 16px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
      ctx.shadowBlur = 4;
      ctx.fillText(ev.year, ex, bandY + dir * 46 + (up ? -26 : 8));
      ctx.restore();

      wrapText(ev.label, ex - 75, bandY + dir * 46 + (up ? -6 : 26), 150, 20, '#f8fafc', 14);
    });
    ops.push({ tool: 'draw_timeline', args });
  }

  // ---- flowchart ---------------------------------------------------------

  function drawFlowchart(args) {
    const { nodes = [], edges = [], title } = args;
    ops = []; redraw();
    if (title) {
      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `700 24px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
      ctx.shadowBlur = 6;
      ctx.fillText(title, W / 2, 38);
      ctx.restore();
    }
    const pos = {};
    for (const n of nodes) {
      const nx = ux(n.x), ny = uy(n.y);
      const nw = uw(n.w ?? 24), nh = uh(n.h ?? 11);
      pos[n.id] = { x: nx, y: ny, w: nw, h: nh };
      const c = inkColor(n.chalk || 'yellow');

      ctx.save();
      ctx.fillStyle = 'rgba(20, 34, 25, 0.9)';
      ctx.strokeStyle = c;
      ctx.lineWidth = 2.8;
      ctx.shadowColor = c;
      ctx.shadowBlur = 5;
      ctx.beginPath();
      const shape = n.shape || 'rect';
      if (shape === 'rect') {
        roundRect(ctx, nx - nw / 2, ny - nh / 2, nw, nh, 8);
      } else if (shape === 'pill' || shape === 'rounded' || shape === 'stadium') {
        roundRect(ctx, nx - nw / 2, ny - nh / 2, nw, nh, nh / 2);
      } else if (shape === 'diamond') {
        ctx.moveTo(nx, ny - nh / 2);
        ctx.lineTo(nx + nw / 2, ny);
        ctx.lineTo(nx, ny + nh / 2);
        ctx.lineTo(nx - nw / 2, ny);
        ctx.closePath();
      } else if (shape === 'ellipse') {
        ctx.ellipse(nx, ny, nw / 2, nh / 2, 0, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.stroke();
      ctx.restore();

      ctx.save();
      ctx.fillStyle = '#f8fafc';
      ctx.font = `700 14px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const labelText = String(n.text || n.label || '');
      ctx.fillText(labelText, nx, ny);
      ctx.restore();
    }

    for (const e of edges) {
      const a = pos[e.from], b = pos[e.to];
      if (!a || !b) continue;
      const c = inkColor(e.chalk || 'white');
      chalkLine(() => {
        ctx.moveTo(a.x, a.y + a.h / 2);
        const midY = (a.y + a.h / 2 + b.y - b.h / 2) / 2;
        ctx.lineTo(a.x, midY);
        ctx.lineTo(b.x, midY);
        ctx.lineTo(b.x, b.y - b.h / 2);
      }, c, 2.6, e.dash);
      arrowHead(b.x, b.y - b.h / 2, b.x, b.y - b.h / 2 - 20, c, 10);
      if (e.label) {
        ctx.save();
        ctx.fillStyle = '#fde047';
        ctx.font = `700 13px 'Segoe UI', sans-serif`;
        ctx.textAlign = 'center';
        ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
        ctx.shadowBlur = 4;
        ctx.fillText(e.label, b.x + 28, (a.y + b.y) / 2);
        ctx.restore();
      }
    }
    ops.push({ tool: 'draw_flowchart', args });
  }

  // ---- show_table --------------------------------------------------------

  function showTable(args) {
    const { headers = [], rows = [], title, highlight_rows = [] } = args;
    ops = []; redraw();
    const padX = 56;
    let y = 52;
    if (title) {
      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `700 24px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.4)';
      ctx.shadowBlur = 6;
      ctx.fillText(title, W / 2, y);
      ctx.restore();
      y += 38;
    }
    const nCols = Math.max(headers.length, ...rows.map(r => r.length), 1);
    const colW = Math.min(200, (W - padX * 2) / nCols);
    const rowH = 42;
    const tableW = colW * nCols;
    const x0 = (W - tableW) / 2;

    // Header
    ctx.save();
    ctx.fillStyle = 'rgba(32, 54, 40, 0.95)';
    ctx.fillRect(x0, y, tableW, rowH);
    ctx.strokeStyle = '#fde047';
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y, tableW, rowH);
    ctx.restore();

    headers.forEach((hd, i) => {
      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `700 15px 'Segoe UI', sans-serif`;
      ctx.textAlign = 'left';
      ctx.shadowColor = 'rgba(253, 224, 71, 0.3)';
      ctx.shadowBlur = 4;
      ctx.fillText(String(hd), x0 + 16 + i * colW, y + 15);
      ctx.restore();
    });
    y += rowH;

    rows.forEach((row, ri) => {
      const hl = highlight_rows.includes(ri);
      ctx.save();
      ctx.fillStyle = hl ? 'rgba(56, 189, 248, 0.18)' : (ri % 2 ? 'rgba(255,255,255,0.03)' : 'transparent');
      ctx.fillRect(x0, y, tableW, rowH);
      ctx.strokeStyle = 'rgba(248, 250, 252, 0.2)';
      ctx.lineWidth = 1;
      ctx.strokeRect(x0, y, tableW, rowH);
      ctx.restore();

      row.forEach((cell, ci) => {
        ctx.save();
        ctx.fillStyle = hl ? '#38bdf8' : '#f8fafc';
        ctx.font = `500 14px 'Segoe UI', sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillText(String(cell), x0 + 16 + ci * colW, y + 14);
        ctx.restore();
      });
      y += rowH;
    });
    ops.push({ tool: 'show_table', args });
  }

  // ---- write_code --------------------------------------------------------

  function writeCode(args) {
    const { code, language = 'python', caption, output } = args;
    ops = []; redraw();
    const padX = 46, padY = caption ? 84 : 46;
    const lines = String(code).split('\n');
    const fs = 15;
    const lh = fs * 1.5;
    const outLines = output ? String(output).split('\n') : [];
    const totalH = padY + lines.length * lh + (output ? 30 + outLines.length * lh : 0) + 30;

    // Dark terminal card
    ctx.save();
    ctx.fillStyle = 'rgba(15, 23, 18, 0.94)';
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.8;
    ctx.shadowColor = '#38bdf8';
    ctx.shadowBlur = 6;
    roundRect(ctx, padX - 14, padY - 34, W - (padX - 14) * 2, totalH - padY + 56, 12, true, true);
    ctx.restore();

    if (caption) {
      ctx.save();
      ctx.fillStyle = '#fde047';
      ctx.font = `700 18px 'Segoe UI', sans-serif`;
      ctx.fillText(caption, padX, padY - 46);
      ctx.restore();
    }

    let yy = padY;
    for (const line of lines) {
      ctx.save();
      ctx.font = `${fs}px Consolas, 'Courier New', monospace`;
      ctx.fillStyle = '#f8fafc';
      ctx.fillText(line, padX, yy);
      ctx.restore();
      yy += lh;
    }

    if (output) {
      ctx.save();
      ctx.fillStyle = '#4ade80';
      ctx.font = `700 14px 'Segoe UI', sans-serif`;
      ctx.fillText('Output:', padX, yy + 14);
      ctx.restore();
      yy += 30;
      ctx.save();
      ctx.fillStyle = '#86efac';
      ctx.font = `${fs}px Consolas, 'Courier New', monospace`;
      for (const l of outLines) { ctx.fillText(l, padX, yy); yy += lh; }
      ctx.restore();
    }
    ops.push({ tool: 'write_code', args });
  }

  function _exec(op, record = true) {
    switch (op.tool) {
      case 'write_text': writeText(op.args); break;
      case 'draw_equation': drawEquation(op.args); break;
      case 'plot_graph': plotGraph(op.args); break;
      case 'draw_diagram': drawDiagram(op.args); break;
      case 'draw_timeline': drawTimeline(op.args); break;
      case 'draw_flowchart': drawFlowchart(op.args); break;
      case 'show_table': showTable(op.args); break;
      case 'write_code': writeCode(op.args); break;
      default: console.warn('Unknown tool:', op.tool);
    }
    if (!record && ops.length) ops.pop();
  }

  return {
    init,
    clear,
    redraw,
    writeText,
    drawEquation,
    plotGraph,
    drawDiagram,
    drawTimeline,
    drawFlowchart,
    showTable,
    writeCode,
    execute: (tool, args) => _exec({ tool, args }),
  };
})();

window.Whiteboard = Whiteboard;
