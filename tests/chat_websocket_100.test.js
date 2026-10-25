/* Deterministic browser-transport regression: 100 chat switches, stale events,
 * stop-before-creation queue cancellation, and reconnect sequence isolation.
 * Run: node tests/chat_websocket_100.test.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Socket {
  static OPEN = 1;
  static latest = null;
  constructor(url) {
    this.url = url;
    this.readyState = Socket.OPEN;
    this.sent = [];
    Socket.latest = this;
  }
  send(message) { this.sent.push(JSON.parse(message)); }
  close() { this.readyState = 3; }
  event(data) { this.onmessage({ data: JSON.stringify(data) }); }
}

let retry;
const context = {
  WebSocket: Socket,
  Auth: { getToken: () => 'test-token' },
  location: { protocol: 'http:', host: 'localhost:8000' },
  console,
  Math,
  Date,
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: (fn) => { retry = fn; return 1; },
  clearTimeout: () => {},
};
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/ws.js'), 'utf8');
const client = vm.runInNewContext(source + '\nRdiWS;', context);
const received = [];
client.on('token', d => received.push(d.text));
client.connect(() => {});
let socket = Socket.latest;
socket.onopen();

for (let i = 0; i < 100; i++) {
  const active = 'current-' + i;
  client.setActiveConversation(active, 0);
  socket.event({ type: 'token', conversation_id: 'stale-' + i, text: 'BAD', seq: 99999 });
  socket.event({ type: 'token', conversation_id: active, text: 'OK-' + i, seq: 1 });
  assert.equal(received.length, i + 1, 'stale event reached active conversation');
  assert.equal(received[i], 'OK-' + i);
}
client.setActiveConversation('current-99', 1);
socket.onclose({ code: 1006 });
assert.equal(typeof retry, 'function');
retry();
socket = Socket.latest;
socket.onopen();
const resume = socket.sent.find(m => m.type === 'resume');
assert.equal(resume.conversation_id, 'current-99');
assert.equal(resume.last_seq, 1, 'old high sequence number polluted resume');

socket.event({ type: 'resume_ok', conversation_id: 'current-99',
               running: true, replayed: 0 });
client.setActiveConversation(null, 0);
socket.event({ type: 'token', conversation_id: 'current-99', text: 'BAD', seq: 2 });
assert.equal(received.length, 100, 'old chat updated New conversation');

socket.readyState = 3;
assert.equal(client.send({ type: 'chat', request_id: 'unsent-turn', conversation_id: null }), false);
assert.equal(client.queuedCount(), 1);
client.dropPending('unsent-turn');
assert.equal(client.queuedCount(), 0, 'new chat could replay cancelled offline work');
client.disconnect();
console.log('PASS: 100 conversation switches; stale events, replay, cancellation queue');
