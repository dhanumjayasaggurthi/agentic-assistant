/* WebSocket client — auto-reconnect w/ exponential backoff, seq-tracked stream
   resume, and offline send queue. Plain JS, no build step.

   Robustness contract with backend/ws_handler.py:
   • Every streamed event carries `seq`. We remember the highest seen per
     conversation; after reconnect we send {type:"resume", conversation_id,
     last_seq} and the server replays anything we missed. A run that kept going
     while we were offline is therefore rendered completely.
   • send() while disconnected queues the message; the queue flushes (in order)
     after resume completes. Nothing the user does mid-outage is lost.
*/

const RdiWS = (() => {
  let _ws = null;
  let _handlers = {};
  let _reconnectTimer = null;
  let _connected = false;
  let _onStatusChange = () => {};
  let _attempt = 0;               // reconnect attempt counter (for backoff + UI)
  let _queue = [];                // messages queued while offline
  let _lastSeq = 0;               // highest seq seen for the active conversation
  let _activeConv = null;         // conversation id whose stream we track
  let _intentionalClose = false;
  let _pingTimer = null;
  let _awaitingResume = false;

  function on(type, fn) { _handlers[type] = fn; }

  function dispatch(data) {
    // A socket may carry late events from a previous conversation. Ignore them
    // BEFORE updating sequence numbers or handing them to React.
    if (data.conversation_id && data.conversation_id !== _activeConv) return;
    if (typeof data.seq === 'number' && data.seq > _lastSeq) _lastSeq = data.seq;
    const fn = _handlers[data.type] || _handlers['*'];
    if (fn) fn(data);

    // Resume/replay must finish before queued user actions are sent. Previously
    // the queue flushed immediately after the resume request, allowing new
    // messages to interleave with replayed stream events.
    if (data.type === 'resume_ok' && _awaitingResume) {
      _awaitingResume = false;
      _flushQueue();
    }
  }

  function setActiveConversation(cid, startSeq) {
    if (_activeConv !== cid) {
      _activeConv = cid;
      _lastSeq = startSeq || 0;
    } else if (typeof startSeq === 'number') {
      _lastSeq = Math.max(_lastSeq, startSeq);
    }
  }

  function _backoffMs() {
    // 0.5s, 1s, 2s, 4s, 8s, then 10s forever ± jitter
    const base = Math.min(10000, 500 * Math.pow(2, Math.min(_attempt, 5)));
    return base + Math.random() * 400;
  }

  function _flushQueue() {
    const q = _queue.slice();
    _queue = [];
    q.forEach(m => send(m));
  }

  function connect(onStatus) {
    _onStatusChange = onStatus || (() => {});
    const token = Auth.getToken();
    if (!token) return;
    _intentionalClose = false;

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url   = `${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`;

    try { _ws = new WebSocket(url); }
    catch (e) { _scheduleReconnect(); return; }

    _ws.onopen = () => {
      _connected = true;
      const wasReconnect = _attempt > 0;
      _attempt = 0;
      if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
      _onStatusChange(wasReconnect ? 'reconnected' : 'connected');
      // Resume the active stream BEFORE flushing user sends, so replayed
      // events arrive in order ahead of new activity.
      if (wasReconnect && _activeConv) {
        _awaitingResume = true;
        _rawSend({ type: 'resume', conversation_id: _activeConv, last_seq: _lastSeq });
      } else {
        _awaitingResume = false;
        _flushQueue();
      }
      // Heartbeat keeps corporate proxies from idling the socket out.
      if (_pingTimer) clearInterval(_pingTimer);
      _pingTimer = setInterval(() => _rawSend({ type: 'ping', ts: Date.now() }), 25000);
    };

    _ws.onmessage = (event) => {
      try { dispatch(JSON.parse(event.data)); }
      catch (e) { console.error('WS parse error', e); }
    };

    _ws.onclose = (e) => {
      _connected = false;
      if (_pingTimer) { clearInterval(_pingTimer); _pingTimer = null; }
      if (_intentionalClose) return;
      if (e.code === 1008) { _onStatusChange('unauthorized'); return; }
      _onStatusChange('disconnected');
      _scheduleReconnect();
    };

    _ws.onerror = () => { _connected = false; _onStatusChange('error'); };
  }

  function _scheduleReconnect() {
    if (_reconnectTimer || _intentionalClose) return;
    _attempt += 1;
    _onStatusChange('reconnecting', _attempt);
    _reconnectTimer = setTimeout(() => {
      _reconnectTimer = null;
      connect(_onStatusChange);
    }, _backoffMs());
  }

  function _rawSend(data) {
    if (_ws && _ws.readyState === WebSocket.OPEN) {
      _ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }

  function send(data) {
    if (_rawSend(data)) return true;
    // Queue everything except ephemeral pings; flushed after reconnect+resume.
    if (data && data.type !== 'ping') _queue.push(data);
    return false;
  }

  function queuedCount() { return _queue.length; }

  function dropPending(requestId) {
    if (requestId) _queue = _queue.filter(m => m.request_id !== requestId);
  }

  function disconnect() {
    _intentionalClose = true;
    if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
    if (_pingTimer) { clearInterval(_pingTimer); _pingTimer = null; }
    if (_ws) { try { _ws.close(); } catch (e) {} _ws = null; }
    _connected = false;
    _queue = [];
    _attempt = 0;
    _awaitingResume = false;
  }

  function isConnected() { return _connected; }

  return { on, connect, send, disconnect, isConnected,
           setActiveConversation, queuedCount, dropPending };
})();
