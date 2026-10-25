/* Regression coverage for the exact Mermaid, JSON and 404 image cases
 * reported in the chat UI. Run with Node; no browser API or provider needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const code = fs.readFileSync(path.join(__dirname, '../frontend/js/rich_content.js'), 'utf8');
const requests = [];
const ctx = {
  window: {},
  fetch: async (url, opts) => {
    requests.push({ url, headers: opts.headers });
    return {
      ok: true,
      blob: async () => ({ type: 'image/png', size: 22 }),
    };
  },
};
const visuals = vm.runInNewContext(code + '\nRdiRichContent;', ctx);

const invalidMermaid = [
  'flowchart TD\n Q[QI-TEST<br>(~17K Rows)] -->|Ingest & Vectorized| DataHub[DataHub]',
  'flowchart LR\n old[Old Table Name<br><code>rdh_haq_haq_query_question</code>] --> new[New Table Name<br>(no client change)]',
  'graph TD\n A[Table: DEV 40K rows] --> B[QI-TEST 17K rows]',
];
for (const original of invalidMermaid) {
  const repaired = visuals.normalizeMermaid(original);
  assert.ok(repaired.includes('["'));
  assert.ok(!repaired.includes('<code>'));
  assert.ok(!repaired.includes('<br>'));
  assert.ok(repaired.includes('] -->') || repaired.includes('] -->|'));
  assert.equal(visuals.normalizeMermaid(repaired), repaired, 'normalization must be idempotent');
}
assert.equal(visuals.normalizeMermaid('flowchart LR\n A["Already quoted"] --> B["Safe"]'),
             'flowchart LR\n A["Already quoted"] --> B["Safe"]');

for (let i = 0; i < 100; i++) {
  const config = JSON.stringify({
    type: i % 3 === 0 ? 'bar' : 'line',
    data: {
      labels: ['DEV', 'QI-TEST'],
      datasets: [{ label: 'Rows', data: [40000 + i, 17000] }],
    },
    options: { plugins: { title: { display: true, text: 'Row Counts' } },
               scales: { y: { beginAtZero: true, title: { display: true, text: 'Rows' } } } },
  });
  const parsed = visuals.parseChart(config, 'json'); // LLM often emits a json fence
  assert.equal(parsed.data.datasets[0].data[0], 40000 + i);
  assert.equal(parsed.options.plugins.title.text, 'Row Counts');
  assert.equal(parsed.options.scales.y.title.text, 'Rows');
}
assert.equal(visuals.parseChart('{"hello":"world"}', 'json'), null);
assert.throws(() => visuals.parseChart('{"type":"bar","data":', 'json'), /invalid JSON/);

for (let i = 0; i < 100; i++) {
  const p = '/images/data_pipeline_' + i + '.png';
  assert.equal(visuals.workspaceImagePath(p), 'images/data_pipeline_' + i + '.png');
  assert.equal(visuals.workspaceImagePath('images/data_pipeline_' + i + '.png'),
               'images/data_pipeline_' + i + '.png');
}
for (const bad of [
  'https://evil.example/graph.png',
  '//evil.example/graph.png', 'data:image/png;base64,AA',
  '/images/../secret.png', '/images/%2E%2E/secret.png',
  '/images/sub%2F..%2Fsecret.png', 'images/a.png?token=unsafe',
  '/images/../../config.ini', '/images/anything.html',
]) assert.equal(visuals.workspaceImagePath(bad), null, bad);

async function run() {
  const blob = await visuals.fetchWorkspaceImage(
    '/images/data_pipeline.png', 'conv-123', { Authorization: 'Bearer test-only' });
  assert.equal(blob.type, 'image/png');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url,
               '/workspace/download/images%2Fdata_pipeline.png?conv_id=conv-123');
  assert.equal(requests[0].headers.Authorization, 'Bearer test-only');
  console.log('PASS: 100 JSON-chart cases, 100 image references, Mermaid repair, authenticated image loading');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
