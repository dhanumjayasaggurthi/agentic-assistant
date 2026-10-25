/* Rich assistant content. Markdown remains the source of truth; enhance only
 * supported fenced diagrams/charts after HTML has been sanitized. */
const RdiRichContent = (() => {
  let sequence = 0;
  let initialized = false;
  const resourceDisposers = new WeakMap();

  function trackResource(root, dispose) {
    const items = resourceDisposers.get(root) || [];
    items.push(dispose);
    resourceDisposers.set(root, items);
  }

  function cleanup(root) {
    for (const dispose of resourceDisposers.get(root) || []) {
      try { dispose(); } catch (_) { /* resources may already be gone */ }
    }
    resourceDisposers.delete(root);
  }

  function isMermaidCode(code, language = '') {
    return language === 'mermaid' ||
      /^(?:graph\s+(?:TD|TB|BT|LR|RL)\b|flowchart\s+(?:TD|TB|BT|LR|RL)\b|sequenceDiagram\b|classDiagram\b|erDiagram\b|stateDiagram(?:-v2)?\b|gantt\b|pie\b|journey\b|mindmap\b|timeline\b|xychart-beta\b)/i.test(code.trimStart());
  }

  function normalizeMermaid(source) {
    // Flowchart labels with HTML or parentheses must be quoted in Mermaid.
    // Repair only simple square-bracket node labels; retain original source.
    return source.replace(/\b([A-Za-z_][\w-]*)\[([^\]\r\n]*)\]/g, (match, id, label) => {
      if (/^"[^"]*"$/.test(label.trim())) return match;
      const clean = label
        .replace(/<br\s*\/?\s*>/gi, ' ')
        .replace(/<\/?(?:code|b|strong|em|i)>/gi, '')
        .replace(/"/g, '&quot;');
      return id + '["' + clean + '"]';
    });
  }

  function parseChart(code, language = '') {
    // LLMs may use json, chart, javascript or no fence language for strict JSON.
    // Parsing remains JSON-only: never evaluate arbitrary JavaScript.
    if (!['chart', 'chartjs', 'json', 'javascript', ''].includes(language)) return null;
    let config;
    try { config = JSON.parse(code); }
    catch (_) {
      if (['chart', 'chartjs'].includes(language) || /"type"\s*:\s*"(?:bar|line|pie|doughnut|scatter)"/.test(code)) {
        throw new Error('Chart configuration is invalid JSON. Regenerate a valid fenced chart JSON block.');
      }
      return null;
    }
    if (!config || !['bar', 'line', 'pie', 'doughnut', 'scatter'].includes(config.type)) return null;
    const input = config.data || {};
    if (!Array.isArray(input.datasets)) return null;
    const count = Math.max((input.labels || []).length,
      ...input.datasets.map(ds => Array.isArray(ds.data) ? ds.data.length : 0));
    if (input.datasets.length > 12 || count > 500) {
      throw new Error('Chart exceeds the 12-series / 500-point browser display limit; source is preserved.');
    }
    const labels = Array.isArray(input.labels) ? input.labels.map(String) : [];
    const datasets = input.datasets.map(ds => ({
      label: String(ds.label || ''),
      data: (Array.isArray(ds.data) ? ds.data : []).map(value => {
        if (config.type === 'scatter' && value && typeof value === 'object') {
          return { x: Number(value.x), y: Number(value.y) };
        }
        return Number.isFinite(Number(value)) ? Number(value) : null;
      }),
    }));
    const options = { responsive: true, maintainAspectRatio: false, animation: false };
    const supplied = config.options || {};
    const title = supplied.plugins?.title;
    if (title && typeof title.text === 'string') {
      options.plugins = { title: { display: title.display !== false, text: title.text.slice(0, 300) } };
    }
    if (supplied.scales && ['bar', 'line', 'scatter'].includes(config.type)) {
      options.scales = {};
      for (const axis of ['x', 'y']) {
        const axisInput = supplied.scales[axis] || {};
        const caption = axisInput.title;
        options.scales[axis] = {
          beginAtZero: axisInput.beginAtZero === true,
          title: { display: caption?.display === true,
                   text: typeof caption?.text === 'string' ? caption.text.slice(0, 100) : '' },
        };
      }
    }
    return { type: config.type, data: { labels, datasets }, options };
  }

  function workspaceImagePath(value) {
    if (typeof value !== 'string') return null;
    let candidate = value.trim();
    if (/^(?:https?:|data:|blob:|file:|\/\/)/i.test(candidate)) return null;
    candidate = candidate.replace(/^\.\//, '').replace(/^\//, '')
      .replace(/^workspace\//, '');
    if (!candidate.startsWith('images/')) return null;
    try { candidate = decodeURIComponent(candidate); } catch (_) { return null; }
    const parts = candidate.split('/');
    if (parts.length < 2 || parts.some(part => !part || part === '.' || part === '..' ||
        /[\\\x00-\x1f?#]/.test(part))) return null;
    if (!/\.(png|jpe?g|webp|gif|svg)$/i.test(candidate)) return null;
    return candidate;
  }

  async function fetchWorkspaceImage(path, conversationId, headers = {}) {
    const safe = workspaceImagePath(path);
    if (!safe || !conversationId) throw new Error('Image is not associated with an active conversation');
    const url = '/workspace/download/' + encodeURIComponent(safe) +
      '?conv_id=' + encodeURIComponent(conversationId);
    const response = await fetch(url, { headers, cache: 'no-store' });
    if (!response.ok) throw new Error('Image file unavailable (HTTP ' + response.status + ')');
    const blob = await response.blob();
    if (!blob.type.startsWith('image/')) throw new Error('Expected an image, received ' + blob.type);
    return blob;
  }

  async function loadWorkspaceImages(root, conversationId, headers = {}) {
    const images = root.querySelectorAll('img[data-rdi-workspace-path]');
    await Promise.all(Array.from(images, async img => {
      if (img.dataset.rdiLoading) return;
      img.dataset.rdiLoading = 'true';
      const path = img.dataset.rdiWorkspacePath;
      try {
        const blob = await fetchWorkspaceImage(path, conversationId, headers);
        if (!img.isConnected) return;
        const url = URL.createObjectURL(blob);
        img.src = url;
        img.hidden = false;
        trackResource(root, () => URL.revokeObjectURL(url));
      } catch (err) {
        if (!img.isConnected) return;
        const info = document.createElement('span');
        info.className = 'rich-error';
        info.textContent = 'Image unavailable (' + path + '): ' + err.message;
        img.replaceWith(info);
      }
    }));
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

  async function enhance(root, conversationId, headers = {}) {
    if (!root) return;
    // Image downloads must not block independent chart/diagram rendering.
    void loadWorkspaceImages(root, conversationId, headers);
    if (window.mermaid && !initialized) {
      window.mermaid.initialize({
        startOnLoad: false, securityLevel: 'strict', theme: 'neutral',
        flowchart: { htmlLabels: false }
      });
      initialized = true;
    }
    for (const codeEl of root.querySelectorAll('pre > code')) {
      const language = (codeEl.className.match(/language-([\w-]+)/) || [,''])[1].toLowerCase();
      const source = codeEl.textContent || '';
      const originalPre = codeEl.parentElement;
      const isDiagram = isMermaidCode(source, language);
      let chart = null;
      try { chart = parseChart(source, language); }
      catch (err) {
        const notice = document.createElement('p');
        notice.className = 'rich-error'; notice.textContent = err.message;
        originalPre?.insertAdjacentElement('afterend', notice);
        continue; // Original full code remains visible and copyable.
      }
      if (!isDiagram && !chart) continue;
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
          const result = await window.mermaid.render(id, normalizeMermaid(source));
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
          trackResource(root, () => instance.destroy());
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

  return { enhance, cleanup, isMermaidCode, normalizeMermaid, parseChart,
           workspaceImagePath, fetchWorkspaceImage, copyImage };
})();
