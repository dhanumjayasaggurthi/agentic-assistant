/* Parse the real reported invalid flowcharts with the same Mermaid major version
 * used by the browser (not a regex-only unit test). */
import mermaid from 'mermaid';
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync('frontend/js/rich_content.js', 'utf8');
const visuals = vm.runInNewContext(source + '\nRdiRichContent;', { window: {} });

mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  flowchart: { htmlLabels: false },
});

const examples = [
  'flowchart TD\n Q[QI-TEST<br>(~17K Rows)] -->|Ingest & Vectorized| DataHub[DataHub]',
  'flowchart LR\n old[Old Table Name<br><code>rdh_haq_haq_query_question</code>] --> new[New Table Name<br>(no client change)]',
  'graph TD\n A[Source DEV 40K rows] --> B[QI-TEST 17K rows]\n B --> C[RA Team]',
];
for (const original of examples) {
  const normalized = visuals.normalizeMermaid(original);
  const result = await mermaid.parse(normalized);
  assert.ok(result, normalized);
}
console.log('PASS: real Mermaid grammar accepts the three screenshot-derived diagrams');
