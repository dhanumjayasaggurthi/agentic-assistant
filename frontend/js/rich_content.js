/* Rich assistant content. Markdown remains the source of truth; enhance only
 * supported fenced diagrams/charts after HTML has been sanitized. */
const RdiRichContent = (() => {
  let sequence = 0;
  let initialized = false;

  function isMermaidCode(code, language = '') {
    return language === 'mermaid' ||
      /^(?:graph\s+(?:TD|TB|BT|LR|RL)\b|flowchart\s+(?:TD|TB|BT|LR|RL)\b|sequenceDiagram\b|classDiagram\b|erDiagram\b|stateDiagram(?:-v2)?\b|gantt\b|pie\b|journey\b|mindmap\b|timeline\b|xychart-beta\b)/i.test(code.trimStart());
  }

  function parseChart(code, language = '') {
    if (!['chart', 'chartjs'].includes(language)) return null;
    let config;
    try { config = JSON.parse(code); } catch (_) { return null; }
    if (!config || !['bar', 'line', 'pie', 'doughnut', 'scatter'].includes(config.type)) return null;
    const input = config.data || {};
    if (!Array.isArray(input.datasets) || input.datasets.length > 12) return null;
    const labels = Array.isArray(input.labels) ? input.labels.map(String).slice(0, 500) : [];
    const datasets = input.datasets.map(ds => ({
      label: String(ds.label || ''),
      data: (Array.isArray(ds.data) ? ds.data : []).slice(0, 500).map(value => {
        if (config.type === 'scatter' && value && typeof value === 'object') {
          return { x: Number(value.x), y: Number(value.y) };
        }
        return Number.isFinite(Number(value)) ? Number(value) : null;
      }),
    }));
    return { type: config.type, data: { labels, datasets },
             options: { responsive: true, maintainAspectRatio: false, animation: false } };
  }

  async function copyPngFromSvg(svg) {
    const xml = new XMLSerializer().serializeToString(svg);
    const url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
    try {
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve; img.onerror = reject; img.src = url;
      });
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.ceil((img.width || 720) * 2));
      canvas.height = Math.max(1, Math.ceil((img.height || 400) * 2));
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      await copyCanvas(canvas);
    } finally { URL.revokeObjectURL(url); }
  }

  async function copyCanvas(canvas) {
    if (!navigator.clipboard || !navigator.clipboard.write || !window.ClipboardItem) {
      throw new Error('Image clipboard requires HTTPS or localhost and a supported browser.');
    }
    const blob = await new Promise((resolve, reject) => canvas.toBlob(
      result => result ? resolve(result) : reject(new Error('Image export failed')), 'image/png'));
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
  }

  async function copyImage(base64, mime = 'image/png') {
    if (!navigator.clipboard || !navigator.clipboard.write || !window.ClipboardItem) {
      throw new Error('Image clipboard requires HTTPS or localhost and a supported browser.');
    }
    const blob = await (await fetch('data:' + mime + ';base64,' + base64)).blob();
    if (blob.type === 'image/png') {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      return;
    }
    const bmp = await createImageBitmap(blob);
    try {
      const canvas = document.createElement('canvas');
      canvas.width = bmp.width; canvas.height = bmp.height;
      canvas.getContext('2d').drawImage(bmp, 0, 0);
      await copyCanvas(canvas);
    } finally { bmp.close(); }
  }

  async function enhance(root) {
    if (!root) return;
    if (window.mermaid && !initialized) {
      window.mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral' });
      initialized = true;
    }
    for (const codeEl of root.querySelectorAll('pre > code')) {
      const language = (codeEl.className.match(/language-([\w-]+)/) || [,''])[1].toLowerCase();
      const source = codeEl.textContent || '';
      const isDiagram = isMermaidCode(source, language);
      const chart = parseChart(source, language);
      if (!isDiagram && !chart) continue;
      const originalPre = codeEl.parentElement;
      if (originalPre.dataset.richRendered) continue;
      originalPre.dataset.richRendered = 'true';
      const figure = document.createElement('figure');
      figure.className = 'rich-figure';
      const graphics = document.createElement('div');
      graphics.className = 'rich-graphic';
      const toolbar = document.createElement('div');
      toolbar.className = 'rich-toolbar';
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = 'Copy image';
      button.className = 'txt-btn rich-copy';
      const sourceView = document.createElement('details');
      sourceView.className = 'rich-source';
      const summary = document.createElement('summary');
      summary.textContent = 'View source';
      sourceView.append(summary, originalPre.cloneNode(true));
      toolbar.append(button, sourceView);
      figure.append(graphics, toolbar);
      originalPre.replaceWith(figure);
      try {
        if (isDiagram) {
          if (!window.mermaid) throw new Error('Diagram renderer unavailable (check corporate CDN access)');
          const id = 'rdi-visual-' + (++sequence);
          const result = await window.mermaid.render(id, source);
          if (!figure.isConnected) continue;
          // SVG from Mermaid is sanitized again before insertion.
          graphics.innerHTML = DOMPurify.sanitize(result.svg, { USE_PROFILES: { svg: true, svgFilters: true } });
          button.onclick = async () => {
            try { await copyPngFromSvg(graphics.querySelector('svg')); button.textContent = 'Copied'; }
            catch (err) { button.textContent = err.message; }
          };
        } else {
          if (!window.Chart) throw new Error('Chart renderer unavailable (check corporate CDN access)');
          const canvas = document.createElement('canvas');
          graphics.classList.add('rich-chart');
          graphics.append(canvas);
          // Chart.js options/data are rebuilt from allowlisted primitive fields.
          const instance = new Chart(canvas, chart);
          button.onclick = async () => {
            try { await copyCanvas(canvas); button.textContent = 'Copied'; }
            catch (err) { button.textContent = err.message; }
          };
          // Cleanup when React replaces the streamed Markdown DOM.
          const observer = new MutationObserver(() => {
            if (!figure.isConnected) { instance.destroy(); observer.disconnect(); }
          });
          observer.observe(root, { childList: true, subtree: true });
        }
      } catch (err) {
        const error = document.createElement('p');
        error.className = 'rich-error';
        error.textContent = 'Visual unavailable: ' + err.message + '. The complete diagram source is below.';
        graphics.append(error);
        sourceView.open = true;
        button.remove();
      }
    }
  }

  return { enhance, isMermaidCode, parseChart, copyImage };
})();
