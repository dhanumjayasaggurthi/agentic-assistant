/* DOM-level integration for rich content, without an external AI gateway.
 * Uses jsdom and a stub Chart renderer; real Mermaid grammar is tested separately. */
import { JSDOM } from 'jsdom';
import createDOMPurify from 'dompurify';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:8000',
});
const { window } = dom;
const { document } = window;
const root = document.getElementById('root');
const DOMPurify = typeof createDOMPurify.sanitize === 'function'
  ? createDOMPurify : createDOMPurify(window);
let chartCreated = false;
let mermaidCalled = false;
const authenticated = [];

window.mermaid = {
  initialize() {},
  async render(id, code) {
    mermaidCalled = true;
    assert.ok(code.includes('["QI-TEST 17K Rows"]'));
    return { svg: '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="120"><text x="10" y="20">QI-TEST</text></svg>' };
  },
};
class Chart {
  constructor(canvas, config) {
    chartCreated = true;
    canvas.dataset.chartRendered = config.data.labels.join(',');
  }
  destroy() {}
}
window.Chart = Chart;
const code = fs.readFileSync('frontend/js/rich_content.js', 'utf8');
const visuals = vm.runInNewContext(code + '\nRdiRichContent;', {
  window, document, DOMPurify, Chart, MutationObserver: window.MutationObserver,
  URL: { createObjectURL: () => 'blob:protected-file', revokeObjectURL: () => {} },
  fetch: async (url, opts) => {
    authenticated.push({ url, headers: opts.headers });
    return { ok: true, blob: async () => new window.Blob(['png'], { type: 'image/png' }) };
  },
});

const diagram = document.createElement('pre');
const diagramCode = document.createElement('code');
diagramCode.className = 'language-mermaid';
diagramCode.textContent = 'flowchart TD\n Q[QI-TEST<br>(~17K Rows)] --> D[DataHub]';
// The expected renderer preserves the underlying model source in the View source panel.
diagram.append(diagramCode);
root.append(diagram);
const chart = document.createElement('pre');
const chartCode = document.createElement('code');
chartCode.className = 'language-json';
chartCode.textContent = JSON.stringify({ type: 'bar', data: {
  labels: ['DEV', 'QI-TEST'], datasets: [{ label: 'Rows', data: [40000, 17000] }],
}});
chart.append(chartCode);
root.append(chart);
const image = document.createElement('img');
image.setAttribute('data-rdi-workspace-path', 'images/data_pipeline.png');
image.hidden = true;
root.append(image);
await visuals.enhance(root, 'conversation-1', { Authorization: 'Bearer fake-token' });
await new Promise(resolve => setTimeout(resolve, 0));
assert.ok(mermaidCalled);
assert.ok(chartCreated);
assert.equal(root.querySelectorAll('.rich-figure').length, 2);
assert.equal(root.querySelectorAll('.rich-source').length, 2);
assert.ok(root.querySelector('.rich-graphic svg text').textContent.includes('QI-TEST'));
assert.equal(root.querySelector('canvas').dataset.chartRendered, 'DEV,QI-TEST');
assert.equal(image.getAttribute('src'), 'blob:protected-file');
assert.equal(image.hidden, false);
assert.deepEqual(authenticated.map(x => x.url),
  ['/workspace/download/images%2Fdata_pipeline.png?conv_id=conversation-1']);
assert.equal(authenticated[0].headers.Authorization, 'Bearer fake-token');
console.log('PASS: DOM renders Mermaid SVG, JSON chart canvas and authenticated workspace image');
