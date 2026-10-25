const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const code = fs.readFileSync(path.join(__dirname, '../frontend/js/rich_content.js'), 'utf8');
const visuals = vm.runInNewContext(code + '\nRdiRichContent;', {
  window: {}, console,
});

assert.equal(visuals.isMermaidCode('graph TD\n A-->B'), true);
assert.equal(visuals.isMermaidCode('flowchart LR\n A-->B'), true);
assert.equal(visuals.isMermaidCode('sequenceDiagram\n A->>B: Hello'), true);
assert.equal(visuals.isMermaidCode('pie\n "Yes": 80'), true);
assert.equal(visuals.isMermaidCode('print("hello")', 'python'), false);
for (let i = 0; i < 100; i++) {
  const json = JSON.stringify({
    type: i % 2 ? 'line' : 'bar',
    data: { labels: ['Dev', 'QA'], datasets: [{label:'records', data:[40000,17000]}] },
  });
  const chart = visuals.parseChart(json, 'chart');
  assert.equal(chart.data.datasets[0].data[1], 17000);
  assert.equal(chart.data.labels[0], 'Dev');
}
assert.equal(visuals.parseChart('{bad json}', 'chart'), null);
assert.equal(visuals.parseChart('{"type":"widget"}', 'chart'), null);
assert.throws(() => visuals.parseChart(JSON.stringify({
  type: 'bar', data: { labels: Array(501).fill('x'), datasets: [{data: Array(501).fill(1)}] },
}), 'chart'), /500-point browser display limit/);
console.log('PASS: 100 chart scenarios, Mermaid recognition, unsafe/oversized fallbacks');
