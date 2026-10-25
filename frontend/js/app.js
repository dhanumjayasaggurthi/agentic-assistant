/* RDI AI — Main React application (JSX via Babel standalone, no build step).
   2026 redesign: warm paper + ink rail + J&J red; permission dock at composer;
   never-break robustness (reconnect+resume, queued sends, model fallback).

   Depends on globals: React, ReactDOM, marked, DOMPurify, Prism, Auth (auth.js),
   RdiWS (ws.js — reconnect/backoff/resume/queue). */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

/* ── Model catalog (JNJ GenAI Marketplace) ─────────────────────────────────── */

const MODEL_GROUPS = [
  {
    group: 'GPT-4.1 (Recommended)',
    models: [
      { id: 'gpt-4.1-global',      name: 'GPT-4.1 Global',      tier: 'standard' },
      { id: 'gpt-4.1-mini-global', name: 'GPT-4.1 Mini',        tier: 'budget'   },
      { id: 'gpt-4.1-nano-global', name: 'GPT-4.1 Nano',        tier: 'budget'   },
    ],
  },
  {
    group: 'GPT-4o',
    models: [
      { id: 'gpt-4o-global',      name: 'GPT-4o Global',      tier: 'standard' },
      { id: 'gpt-4o-mini-global', name: 'GPT-4o Mini Global', tier: 'budget'   },
    ],
  },
  {
    group: 'GPT-5',
    models: [
      { id: 'gpt-5-global',        name: 'GPT-5 Global',      tier: 'ultra'    },
      { id: 'gpt-5.5-global',      name: 'GPT-5.5 Global',    tier: 'ultra'    },
      { id: 'gpt-5-mini-global',   name: 'GPT-5 Mini Global', tier: 'premium'  },
      { id: 'gpt-5.4-global',      name: 'GPT-5.4 Global',    tier: 'premium'  },
      { id: 'gpt-5.4-mini-global', name: 'GPT-5.4 Mini',      tier: 'standard' },
      { id: 'gpt-5.4-nano-global', name: 'GPT-5.4 Nano',      tier: 'budget'   },
      { id: 'gpt-5-nano-global',   name: 'GPT-5 Nano Global', tier: 'budget'   },
    ],
  },
  {
    group: 'Reasoning (o-series)',
    models: [
      { id: 'o4-mini-global', name: 'o4-mini Global', tier: 'premium' },
      { id: 'o3-global',      name: 'o3 Global',      tier: 'ultra'   },
      { id: 'o3-mini-global', name: 'o3-mini Global', tier: 'premium' },
      { id: 'o3-pro-global',  name: 'o3-pro Global',  tier: 'ultra'   },
    ],
  },
  {
    group: 'Codex (Deep Reasoning Code)',
    models: [
      { id: 'gpt-5.3-codex-global',      name: 'GPT-5.3 Codex',      tier: 'premium',  noTools: true },
      { id: 'gpt-5.1-codex-global',      name: 'GPT-5.1 Codex',      tier: 'premium',  noTools: true },
      { id: 'gpt-5.1-codex-mini-global', name: 'GPT-5.1 Codex Mini', tier: 'standard', noTools: true },
      { id: 'gpt-5.2-codex-global',      name: 'GPT-5.2 Codex',      tier: 'premium',  noTools: true },
    ],
  },
  {
    group: 'Image Generation',
    models: [
      { id: 'gpt-image-2-global',      name: 'DALL-E (gpt-image-2)',   tier: 'premium',  type: 'image', noTools: true },
      { id: 'gpt-image-1.5-global',    name: 'DALL-E (gpt-image-1.5)', tier: 'premium',  type: 'image', noTools: true },
      { id: 'gpt-image-1-global',      name: 'DALL-E (gpt-image-1)',   tier: 'standard', type: 'image', noTools: true },
      { id: 'gpt-image-1-mini-global', name: 'DALL-E Mini',            tier: 'budget',   type: 'image', noTools: true },
      { id: 'gemini-2.5-flash-image',  name: 'Imagen (Gemini)',        tier: 'standard', type: 'image', noTools: true },
    ],
  },
  {
    group: 'Claude (Bedrock)',
    models: [
      { id: 'us.anthropic.claude-sonnet-4-6',              name: 'Claude Sonnet 4.6',     tier: 'standard' },
      { id: 'us.anthropic.claude-opus-4-8',                name: 'Claude Opus 4.8',       tier: 'ultra'    },
      { id: 'us.anthropic.claude-haiku-4-5-20251001-v1:0', name: 'Claude Haiku 4.5',      tier: 'budget'   },
      { id: 'global.anthropic.claude-opus-4-8',            name: 'Claude Opus 4.8 (G)',   tier: 'ultra'    },
      { id: 'global.anthropic.claude-sonnet-4-6',          name: 'Claude Sonnet 4.6 (G)', tier: 'standard' },
    ],
  },
  {
    group: 'Llama (Bedrock)',
    models: [
      { id: 'us.meta.llama3-3-70b-instruct-v1:0', name: 'Llama 3.3 70B', tier: 'standard' },
      { id: 'us.meta.llama3-2-90b-instruct-v1:0', name: 'Llama 3.2 90B', tier: 'budget'   },
    ],
  },
  {
    group: 'Gemini (Vertex)',
    models: [
      { id: 'gemini-2.5-pro',        name: 'Gemini 2.5 Pro',        tier: 'premium' },
      { id: 'gemini-2.5-flash',      name: 'Gemini 2.5 Flash',      tier: 'budget'  },
      { id: 'gemini-2.5-flash-lite', name: 'Gemini 2.5 Flash Lite', tier: 'budget'  },
    ],
  },
];

const ALL_MODELS = MODEL_GROUPS.flatMap(g => g.models);
let RUNTIME_MODEL_MAP = {};
const modelById = id => RUNTIME_MODEL_MAP[id] || ALL_MODELS.find(m => m.id === id);
const modelName = id => (modelById(id) || {}).name || id;
const isImageModel = id => {
  const m = modelById(id) || {};
  return m.type === 'image' || !!(m.capabilities || {}).image_generation;
};
const isNoToolsModel = id => {
  const live = RUNTIME_MODEL_MAP[id];
  if (live && live.capabilities) return !live.capabilities.tools;
  const m = (id || '').toLowerCase();
  if ((modelById(id) || {}).noTools) return true;
  if (m.startsWith('o1') || m.startsWith('o3') || m.startsWith('o4')) return true;
  if (m.startsWith('gemini-') && m !== 'gemini-2.5-flash-image') return true;
  return false;
};

const TIER_COLORS = { budget: '#1B7F4D', standard: '#B45309', premium: '#6B5CD6', ultra: '#E11900' };
const TIERS = ['all', 'budget', 'standard', 'premium', 'ultra'];

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function groupByDate(convs) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);
  const week = new Date(today); week.setDate(today.getDate() - 7);
  const g = { Today: [], Yesterday: [], 'Last 7 days': [], Earlier: [] };
  convs.forEach(c => {
    const d = new Date(c.updated_at + (c.updated_at.endsWith('Z') ? '' : 'Z'));
    if (d >= today) g.Today.push(c);
    else if (d >= yesterday) g.Yesterday.push(c);
    else if (d >= week) g['Last 7 days'].push(c);
    else g.Earlier.push(c);
  });
  return Object.entries(g).filter(([, v]) => v.length);
}

function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

function fmtBytes(n) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

function renderMarkdown(text) {
  try {
    const html = marked.parse(text || '', { breaks: true, gfm: true });
    const safe = DOMPurify.sanitize(html, { ADD_ATTR: ['target'] });
    // Prevent the browser from requesting nonexistent public /images paths.
    // Images are authenticated workspace assets loaded after Markdown mounts.
    const template = document.createElement('template');
    template.innerHTML = safe;
    for (const img of template.content.querySelectorAll('img[src]')) {
      const relative = RdiRichContent.workspaceImagePath(img.getAttribute('src'));
      if (!relative) continue;
      img.removeAttribute('src');
      img.setAttribute('data-rdi-workspace-path', relative);
      img.hidden = true;
    }
    return { __html: template.innerHTML };
  } catch (e) {
    return { __html: DOMPurify.sanitize((text || '').replace(/</g, '&lt;')) };
  }
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

async function fetchBlobURL(url) {
  const res = await fetch(url, { headers: Auth.authHeaders() });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

function downloadBlob(url, filename) {
  fetch(url, { headers: Auth.authHeaders() })
    .then(r => r.blob())
    .then(b => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    });
}

/* ── Icons (inline, stroke = currentColor) ─────────────────────────────────── */

const Ic = {
  chat: () => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="3" width="14" height="11" rx="3" /><line x1="6" y1="7.5" x2="12" y2="7.5" /><line x1="6" y1="10.5" x2="10" y2="10.5" />
    </svg>),
  agent: () => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="4.6" y="4.6" width="8.8" height="8.8" rx="1.5" transform="rotate(45 9 9)" /><circle cx="9" cy="9" r="1.4" fill="currentColor" stroke="none" />
    </svg>),
  folder: () => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M2 5.5C2 4.7 2.7 4 3.5 4H7l1.5 2h6C15.3 6 16 6.7 16 7.5v5C16 13.3 15.3 14 14.5 14h-11C2.7 14 2 13.3 2 12.5v-7Z" />
    </svg>),
  admin: () => (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="9" cy="9" r="6.5" /><circle cx="9" cy="9" r="2" fill="currentColor" stroke="none" />
    </svg>),
  sun: () => (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="8" r="4" /><path d="M8 0.8v1.6M8 13.6v1.6M0.8 8h1.6M13.6 8h1.6M2.9 2.9l1.1 1.1M12 12l1.1 1.1M13.1 2.9L12 4M4 12l-1.1 1.1" />
    </svg>),
  plus: () => (
    <svg width="12" height="12" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.8" fill="none">
      <line x1="6" y1="1" x2="6" y2="11" /><line x1="1" y1="6" x2="11" y2="6" />
    </svg>),
  send: () => (
    <svg width="12" height="12" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.7">
      <path d="M6.5 11V2M2.5 6L6.5 2l4 4" />
    </svg>),
  stop: () => (
    <svg width="10" height="10" viewBox="0 0 10 10"><rect width="10" height="10" rx="2" fill="currentColor" /></svg>),
  clip: () => (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M12.5 6.3 7.6 11.2a3.4 3.4 0 0 1-4.8-4.8L7.6 1.6a2.3 2.3 0 0 1 3.2 3.2L6 9.6a1.1 1.1 0 0 1-1.6-1.6l4.4-4.4" />
    </svg>),
  mic: () => (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="5" y="1" width="4" height="7" rx="2" /><path d="M2.5 6.5a4.5 4.5 0 0 0 9 0M7 11v2" />
    </svg>),
  speaker: () => (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M2 5.5v3h2.5L8 11V3L4.5 5.5H2Z" /><path d="M10 5a3 3 0 0 1 0 4" />
    </svg>),
  search: () => (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6.5" cy="6.5" r="4.5" /><line x1="10" y1="10" x2="13.5" y2="13.5" />
    </svg>),
  down: () => (
    <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" strokeWidth="1.2">
      <path d="M1.5 3l2.5 2.5L6.5 3" />
    </svg>),
  dl: () => (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M6 1v7M3 5.5 6 8.5l3-3M1.5 10.5h9" />
    </svg>),
  link: () => (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M5 7a2.5 2.5 0 0 0 3.5 0l2-2a2.5 2.5 0 0 0-3.5-3.5l-1 1M7 5a2.5 2.5 0 0 0-3.5 0l-2 2a2.5 2.5 0 0 0 3.5 3.5l1-1" />
    </svg>),
  cols: () => (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="1" y="1.5" width="10" height="9" rx="1.5" /><line x1="7.5" y1="1.5" x2="7.5" y2="10.5" />
    </svg>),
  play: () => (
    <svg width="12" height="12" viewBox="0 0 12 12" fill="var(--red)"><path d="M2.5 1.5 10 6 2.5 10.5Z" /></svg>),
};

/* ── Toasts ────────────────────────────────────────────────────────────────── */

let _toastId = 0;
function Toasts({ toasts }) {
  return (
    <div className="toasts">
      {toasts.map(t => <div key={t.id} className={'toast' + (t.err ? ' err' : '')}>{t.text}</div>)}
    </div>
  );
}

/* ── Login ─────────────────────────────────────────────────────────────────── */

function Login({ onAuthed }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => { Auth.getSSOConfig().then(c => setSsoEnabled(!!c.enabled)); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      await Auth.loginPassword(username, password);
      onAuthed();
    } catch (err) {
      setError(err.message || 'Invalid credentials');
    } finally { setBusy(false); }
  };

  const sso = async () => {
    setBusy(true); setError('');
    try { await Auth.loginSSO(); onAuthed(); }
    catch (err) { setError(err.message || 'SSO sign-in failed'); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-accent" />
        <form className="login-body" onSubmit={submit}>
          <div className="login-logo">R</div>
          <div className="login-title">RDI AI</div>
          <div className="login-sub">Research &amp; Development Intelligence</div>
          {error && <div className="login-error">{error}</div>}
          <div className="login-field">
            <label className="login-label">Username</label>
            <input className="login-input" value={username} onChange={e => setUsername(e.target.value)}
                   autoFocus autoComplete="username" placeholder="j.doe" />
          </div>
          <div className="login-field">
            <label className="login-label">Password</label>
            <input className="login-input" type="password" value={password}
                   onChange={e => setPassword(e.target.value)} autoComplete="current-password" placeholder="••••••••" />
          </div>
          <button className="login-submit" disabled={busy} type="submit">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
          {ssoEnabled && (
            <React.Fragment>
              <div className="login-or"><div className="line" />OR<div className="line" /></div>
              <button type="button" className="login-ms" onClick={sso} disabled={busy}>
                <svg width="14" height="14" viewBox="0 0 14 14">
                  <rect width="6.3" height="6.3" fill="#F35325" /><rect x="7.7" width="6.3" height="6.3" fill="#81BC06" />
                  <rect y="7.7" width="6.3" height="6.3" fill="#05A6F0" /><rect x="7.7" y="7.7" width="6.3" height="6.3" fill="#FFBA08" />
                </svg>
                Continue with Microsoft
              </button>
            </React.Fragment>
          )}
        </form>
        <div className="login-foot">INTERNAL TOOL · JNJ GENAI MARKETPLACE · {ALL_MODELS.length} MODELS</div>
      </div>
    </div>
  );
}

/* ── Model palette (⌘K) ────────────────────────────────────────────────────── */

function ModelPalette({ open, onClose, current, onPick, agentMode }) {
  const [q, setQ] = useState('');
  const [tier, setTier] = useState('all');
  const inputRef = useRef(null);

  useEffect(() => { if (open) { setQ(''); setTier('all'); setTimeout(() => inputRef.current && inputRef.current.focus(), 30); } }, [open]);

  if (!open) return null;

  const ql = q.toLowerCase();
  const groups = MODEL_GROUPS
    .map(g => ({
      group: g.group,
      models: g.models.filter(m =>
        (tier === 'all' || m.tier === tier) &&
        (!ql || m.id.toLowerCase().includes(ql) || m.name.toLowerCase().includes(ql) || g.group.toLowerCase().includes(ql))),
    }))
    .filter(g => g.models.length);

  return (
    <div className="palette-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette">
        <div className="palette-head">
          <Ic.search />
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
                 placeholder={`Search ${ALL_MODELS.length} models — try "claude" or "codex"`}
                 onKeyDown={e => { if (e.key === 'Escape') onClose(); }} />
          <button className="kbd" onClick={onClose}>ESC</button>
        </div>
        <div className="palette-tiers">
          {TIERS.map(t => (
            <button key={t} className={'tier-chip' + (tier === t ? ' on' : '')} onClick={() => setTier(t)}>
              {t.toUpperCase()}
            </button>
          ))}
          <span className="spacer" />
          {agentMode && <span className="mono" style={{ fontSize: 10, color: 'var(--warn)' }}>agent mode — needs tool support</span>}
        </div>
        <div className="palette-list">
          {groups.map(g => (
            <div key={g.group}>
              <div className="palette-group">{g.group}</div>
              {g.models.map(m => {
                const live = modelById(m.id) || m;
                const unavailable = live.available === false;
                return (
                  <div key={m.id}
                       className={'model-row' + (m.id === current ? ' sel' : '')}
                       style={unavailable ? { opacity: 0.48, cursor: 'not-allowed' } : null}
                       onClick={() => { if (!unavailable) onPick(m.id); }}>
                    <span className="model-dot" style={{ background: TIER_COLORS[live.tier || m.tier] }} />
                    <span className="model-name">{live.name || m.name}</span>
                    <span className="model-id">{m.id}</span>
                    {unavailable && <span className="no-tools-badge" title="Provider is not configured at runtime">OFFLINE</span>}
                    {!unavailable && isNoToolsModel(m.id) && <span className="no-tools-badge" title="This integration uses a separate tool-capable orchestrator for Agent mode">SPECIALIST</span>}
                    <span className="model-tier" style={{ color: TIER_COLORS[live.tier || m.tier] }}>{(live.tier || m.tier).toUpperCase()}</span>
                  </div>
                );
              })}
            </div>
          ))}
          {!groups.length && <div style={{ padding: 24, textAlign: 'center' }} className="dim">No models match</div>}
        </div>
        <div className="palette-foot">
          <span>{ALL_MODELS.length} models</span><span>JNJ GenAI Marketplace</span>
          <span className="spacer" /><span>↵ select</span><span>esc close</span>
        </div>
      </div>
    </div>
  );
}

/* ── Run card (agent step timeline inside the thread) ──────────────────────── */

function RunCard({ run }) {
  const [openIdx, setOpenIdx] = useState(null);
  if (!run || !run.steps || !run.steps.length) return null;
  const doneCount = run.steps.filter(s => s.status === 'done').length;
  return (
    <div className="run-card">
      <div className="run-head">
        <Ic.play />
        <span className="run-title">Agent run</span>
        <span className="run-progress">{doneCount}/{run.steps.length} steps</span>
        <span className="run-note">
          {run.final === 'error' ? 'stopped on error' :
           run.final === 'done' ? 'complete' : 'running — safe to reload'}
        </span>
      </div>
      {run.steps.map((s, i) => (
        <React.Fragment key={s.rid || i}>
          <div className="run-step" onClick={() => setOpenIdx(openIdx === i ? null : i)}>
            <span className={'step-dot ' + (s.status === 'waiting_permission' ? 'running' : (s.status || ''))} />
            <span className="step-tool">{s.tool}</span>
            <span className="step-desc">
              {s.status === 'waiting_permission' ? 'waiting for you — respond at the composer below ↓' : (s.label || '')}
            </span>
            {s.duration_ms != null && <span className="step-time">{(s.duration_ms / 1000).toFixed(1)}s</span>}
          </div>
          {openIdx === i && (s.result_preview || s.args_preview) && (
            <div className="step-out">{s.result_preview || s.args_preview}</div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

/* ── User-visible progress (status/tool events, not hidden model reasoning) ── */

function ActivityPanel({ events = [], live = false, run = null }) {
  const [expanded, setExpanded] = useState(live);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!live) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, [live]);
  if (!live && !events.length && !run) return null;
  const current = events.length ? events[events.length - 1].action : 'Preparing response…';
  return (
    <div className="activity-panel">
      <button type="button" className="activity-toggle" aria-expanded={expanded}
              onClick={() => setExpanded(value => !value)}>
        {live && <span className="activity-pulse" aria-label="In progress" />}
        <span className="activity-summary">{live ? current : 'View completed activity'}</span>
        <span className="activity-toggle-hint">{live ? elapsed + 's · ' : ''}{expanded ? 'Hide details' : 'Show details'}</span>
        <Ic.down />
      </button>
      {expanded && (
        <div className="activity-details" role="status" aria-live="polite">
          {(events.length ? events : [{ action: 'Preparing response…' }]).map((event, index) => (
            <div className="activity-entry" key={index}>
              <span aria-hidden="true">{event.icon || '·'}</span>
              <span>{event.action}</span>
            </div>
          ))}
          {run && <RunCard run={run} />}
          {live && <span className="activity-still-running">Working — you can stop this response at any time.</span>}
        </div>
      )}
    </div>
  );
}

/* ── Message ───────────────────────────────────────────────────────────────── */

function Message({ msg, onSpeak, onImageClick, streaming, conversationId }) {
  const bodyRef = useRef(null);
  useEffect(() => {
    // Streaming text stays incremental. Parse charts, SVG and workspace images
    // only when the completed fenced block is stable, avoiding repeated work.
    if (streaming) return;
    const timer = setTimeout(() => {
      if (!bodyRef.current) return;
      RdiRichContent.enhance(bodyRef.current, conversationId, Auth.authHeaders());
      if (window.Prism) bodyRef.current.querySelectorAll('pre code').forEach(el => {
        try { Prism.highlightElement(el); } catch (e) {}
      });
    }, 0);
    return () => clearTimeout(timer);
  }, [msg.content, streaming, conversationId]);

  if (msg.role === 'user') {
    return (
      <div className="msg-user">
        <div className="msg-user-bubble">
          {(msg.attachments || []).map((a, i) => (
            <span className="msg-att" key={i}><span className="ok-sq">▪</span> {a.name}</span>
          ))}
          <div className="msg-user-content" dangerouslySetInnerHTML={renderMarkdown(msg.content || '')} />
        </div>
      </div>
    );
  }

  const images = (msg.attachments || []).filter(a => (a.type || '').startsWith('image'));
  return (
    <div className="msg-ai">
      <div className="msg-ai-head">
        <span className="msg-ai-star">✳</span>
        <span className="msg-ai-name">RDI AI</span>
        <span className="msg-ai-meta">{msg.meta || ''}</span>
      </div>
      {(streaming || (msg.activity || []).length > 0 || msg.run) &&
        <ActivityPanel live={!!streaming} events={msg.activity || []} run={msg.run} />}
      {images.length > 0 && (
        <div className={'img-grid ' + (images.length === 1 ? 'g1' : images.length === 2 ? 'g2' : '')} style={{ marginBottom: 14 }}>
          {images.map((a, i) => (
            <div className="img-cell" key={i} onClick={() => onImageClick(a)}>
              <img src={`data:${a.type || 'image/png'};base64,${a.content}`} alt={a.name} />
              <div className="img-cell-bar">
                <span className="lbl">{a.name}</span>
                <button onClick={async e => {
                  e.stopPropagation();
                  try { await RdiRichContent.copyImage(a.content, a.type || 'image/png'); }
                  catch (err) { alert('Cannot copy image: ' + err.message); }
                }}>copy image</button>
                <button onClick={e => { e.stopPropagation(); onImageClick(a, 'edit'); }}>edit</button>
                <button onClick={e => { e.stopPropagation(); onImageClick(a, 'vary'); }}>vary</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {(msg.content || streaming) && <div className="msg-body" ref={bodyRef}>
        {msg.content && <div className="msg-markdown" dangerouslySetInnerHTML={renderMarkdown(msg.content)} />}
        {streaming && !msg.content && <span className="msg-pending">Response in progress…</span>}
        {streaming && !!msg.content && <span className="stream-caret" aria-hidden="true" />}
      </div>}
      {!streaming && msg.content && (
        <div className="msg-actions">
          <button className="txt-btn" onClick={async () => {
            try { await navigator.clipboard.writeText(msg.content); }
            catch (err) { alert('Text copy unavailable: ' + err.message); }
          }}>copy text</button>
          <button className="txt-btn" onClick={async () => {
            try {
              if (!navigator.clipboard?.write || !window.ClipboardItem) throw new Error('Rich copy needs HTTPS or localhost');
              await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([bodyRef.current?.innerHTML || ''], { type: 'text/html' }),
                'text/plain': new Blob([msg.content], { type: 'text/plain' }),
              })]);
            } catch (err) { alert('Rich copy unavailable: ' + err.message); }
          }}>copy formatted</button>
          <button className="txt-btn" onClick={() => onSpeak(msg.content)}>speak</button>
        </div>
      )}
    </div>
  );
}

/* ── Composer (attachments w/ retry, voice, model chip, send) ──────────────── */

function Composer({ conv, agentMode, model, onOpenModel, onSend, onStop, busy, disabled,
                    attachments, setAttachments, guard, onGuardDismiss, onGuardChat,
                    permission, onPermission, autoAllow, onAutoAllow, uploadFile }) {
  const [text, setText] = useState('');
  const [recording, setRecording] = useState(false);
  const taRef = useRef(null);
  const fileRef = useRef(null);
  const recRef = useRef(null);

  const grow = () => {
    const ta = taRef.current; if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = Math.min(220, ta.scrollHeight) + 'px';
  };

  const submit = () => {
    const ready = attachments.filter(a => a.status === 'done');
    if ((!text.trim() && !ready.length) || busy || disabled) return;
    onSend(text.trim(), ready);
    setText('');
    setAttachments([]);
    if (taRef.current) taRef.current.style.height = 'auto';
  };

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  };

  const pickFiles = (e) => {
    [...e.target.files].forEach(f => uploadFile(f));
    e.target.value = '';
  };

  const onPaste = e => {
    // Retain normal pasted text. Upload clipboard images/files as attachments.
    const files = [...(e.clipboardData?.items || [])]
      .filter(item => item.kind === 'file')
      .map(item => item.getAsFile())
      .filter(Boolean);
    if (!files.length) return;
    e.preventDefault();
    files.forEach((file, index) => {
      const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
      const needsName = !file.name || file.name === 'image.png' || file.name === 'blob';
      uploadFile(needsName
        ? new File([file], `pasted-${Date.now()}-${index}.${ext}`, { type: file.type })
        : file);
    });
  };

  const toggleRec = async () => {
    if (recording) {
      recRef.current && recRef.current.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks = [];
      rec.ondataavailable = e => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunks, { type: 'audio/webm' });
        const b64 = await new Promise(res => {
          const r = new FileReader();
          r.onloadend = () => res(r.result.split(',')[1]);
          r.readAsDataURL(blob);
        });
        RdiWS.send({ type: 'transcribe', audio_base64: b64, audio_format: 'webm' });
      };
      rec.start();
      recRef.current = rec;
      setRecording(true);
    } catch (e) { /* mic denied */ }
  };

  // Transcription result → append to input
  useEffect(() => {
    RdiWS.on('transcription', d => {
      setText(t => (t ? t + ' ' : '') + (d.text || ''));
      setTimeout(grow, 10);
    });
  }, []);

  const m = modelById(model) || {};
  const imgMode = m.type === 'image';
  const placeholder = imgMode
    ? 'Describe the image you want to generate…'
    : agentMode
      ? 'Ask the agent to build, analyze, search, or create files and images…'
      : 'Message RDI AI…';

  return (
    <div className="composer-wrap">
      <div className="composer-inner">
        {permission && (
          <div className="perm-dock">
            <div className="perm-row">
              <span className="sq warn" />
              <span className="perm-text">
                <strong>Approval needed</strong> — the agent wants to run <span className="perm-tool mono">{permission.tool}</span>
              </span>
              <span className="spacer" />
              <button className="btn-allow" onClick={() => onPermission('allow')}>Allow</button>
              <button className="btn-allow" title={`Always approve ${permission.tool} while this conversation is active`}
                      onClick={() => onPermission('allow', true)}>Always Allow</button>
              <button className="btn-deny" onClick={() => onPermission('deny')}>Deny</button>
            </div>
            {permission.preview && <div className="perm-code">{permission.preview}</div>}
            <div className="perm-sub">
              <span className="perm-preview">writes to this conversation's workspace only</span>
              <label className="perm-auto">
                <input type="checkbox" checked={autoAllow} onChange={e => onAutoAllow(e.target.checked)} />
                auto-approve read-only tools
              </label>
            </div>
          </div>
        )}
        {guard && (
          <div className="guard-banner">
            <span className="sq" />
            <span style={{ flex: 1 }}>
              <strong>{modelName(guard)}</strong> is a specialist in this integration — Agent mode will use a tool-capable premium orchestrator while keeping specialist capabilities available.
            </span>
            <button className="guard-btn" onClick={onGuardChat}>use it in Chat →</button>
            <button className="guard-btn" onClick={onGuardDismiss}>ok</button>
          </div>
        )}
        <div className={'composer' + (guard ? ' guarded' : '')}>
          {attachments.length > 0 && (
            <div className="att-row">
              {attachments.map(a => (
                <span key={a.key} className={'att-chip ' + a.status}>
                  <span className="sq" style={{ background: a.status === 'done' ? 'var(--ok)' : a.status === 'failed' ? 'var(--red)' : 'var(--warn)' }} />
                  {a.name}{a.status === 'uploading' ? ' — uploading…' : a.status === 'failed' ? ' — upload failed' : ''}
                  {a.status === 'failed' && <button className="att-retry" onClick={() => uploadFile(a.file, a.key)}>retry</button>}
                  <button className="x" onClick={() => setAttachments(list => list.filter(x => x.key !== a.key))}>✕</button>
                </span>
              ))}
            </div>
          )}
          <textarea ref={taRef} rows="1" value={text} placeholder={placeholder}
                    onChange={e => { setText(e.target.value); grow(); }} onKeyDown={onKey}
                    onPaste={onPaste} disabled={disabled} />
          <div className="composer-tools">
            <input ref={fileRef} type="file" multiple style={{ display: 'none' }} onChange={pickFiles} />
            <button className="tool-btn" title="Attach files" onClick={() => fileRef.current.click()}><Ic.clip /></button>
            <button className="model-chip" onClick={onOpenModel} title="Choose model (⌘K)">
              <span className="model-dot" style={{ background: TIER_COLORS[m.tier] || 'var(--ink3)' }} />
              {m.name || model}
              <Ic.down />
            </button>
            {agentMode && !imgMode && <span className="tools-pill">tools ready</span>}
            <span className="spacer" />
            <button className={'tool-btn' + (recording ? ' rec' : '')} title="Voice input" onClick={toggleRec}><Ic.mic /></button>
            {busy
              ? <button className="btn-send" title="Stop" onClick={onStop}><Ic.stop /></button>
              : <button className="btn-send" title="Send" onClick={submit}
                        disabled={disabled || (!text.trim() && !attachments.some(a => a.status === 'done'))}><Ic.send /></button>}
          </div>
        </div>
        <div className="composer-hints">
          <span>⏎ send</span><span>⇧⏎ newline</span><span>⌘K models</span>
        </div>
      </div>
    </div>
  );
}

/* ── Chat / Agent view ─────────────────────────────────────────────────────── */

function ChatView(props) {
  const { conv, messages, streamText, streamRun, busy, activity, user, agentMode, setAgentMode,
          onSend, permission, onPermission, model, connState } = props;
  const scrollRef = useRef(null);
  const pinnedRef = useRef(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, streamText, streamRun, activity, busy]);

  const onScroll = () => {
    const el = scrollRef.current; if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const speak = (text) => RdiWS.send({ type: 'tts', text: text.slice(0, 2000), voice: localStorage.getItem('rdi_voice') || 'nova' });

  const empty = !conv && !messages.length && !streamText;

  return (
    <React.Fragment>
      {empty ? (
        <div className="home-scroll">
          <div className="home-inner">
            <div className="home-greeting">{greeting()}, {user.display_name.split(' ')[0]}.</div>
            <div className="home-sub">{agentMode ? 'Agent mode — I plan, run tools, and build files. Every step is visible.' : 'What are we working on?'}</div>
            {props.composer}
            {props.recent.length > 0 && (
              <React.Fragment>
                <div className="home-section">Continue</div>
                {props.recent.slice(0, 3).map(c => (
                  <div className="home-row" key={c.id} onClick={() => props.onOpenConv(c.id)}>
                    <span className="title">{c.title}</span>
                    <span className="tag">{relTime(c.updated_at)}</span>
                    <span className="arrow">→</span>
                  </div>
                ))}
              </React.Fragment>
            )}
            <div className="home-section tight">Try</div>
            {(agentMode ? [
              'Run a Python analysis on my trial data and chart the outcomes',
              'Build a PowerPoint on AI adoption in pharma R&D',
              'Generate 3 premium hero images and build a client-ready deck with them',
              'Search the web and summarize the latest on mRNA vaccines',
            ] : [
              'Explain a technical concept clearly',
              'Summarize and extract key points from a document',
              'Write a clinical research summary',
              'Translate regulatory text into plain language',
            ]).map((s, i) => (
              <div className="home-row" key={i} onClick={() => props.onSuggestion(s)}>
                <span className="title" style={{ color: 'var(--ink2)' }}>{s}</span>
                <span className="arrow">→</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
          <div className="chat-inner">
            {messages.map((m, i) => (
              <Message key={i} msg={m} conversationId={conv}
                       onSpeak={speak} onImageClick={props.onImageClick} />
            ))}
            {(busy || streamText || streamRun) && (
              <Message msg={{ role: 'assistant', content: streamText, run: streamRun,
                              activity, meta: modelName(model) }}
                       conversationId={conv}
                       onSpeak={speak} onImageClick={props.onImageClick} streaming={busy} />
            )}
          </div>
        </div>
      )}
      {!empty && props.composer}
    </React.Fragment>
  );
}

/* ── Run rail (right side stats) ───────────────────────────────────────────── */

function RunRail({ run, artifacts, onClose, onOpenWorkspace, model }) {
  const steps = (run && run.steps) || [];
  return (
    <div className="run-rail">
      <div className="run-rail-head">
        <span className="run-rail-title">Run detail</span>
        <button className="x-btn" onClick={onClose}>✕</button>
      </div>
      <div className="run-rail-body">
        <div className="stat-card">
          <div className="stat-row"><span className="k">model</span><span className="v">{model}</span></div>
          <div className="stat-row"><span className="k">status</span><span className="v">{run ? (run.final || 'running') : 'idle'}</span></div>
          <div className="stat-row"><span className="k">steps</span><span className="v">{steps.length}</span></div>
        </div>
        {steps.length > 0 && (
          <React.Fragment>
            <div className="rail-section">Timeline</div>
            <div style={{ marginBottom: 16 }}>
              {steps.map((s, i) => (
                <div className="tl-row" key={i}>
                  <span className={'step-dot ' + (s.status === 'waiting_permission' ? 'running' : (s.status || ''))} />
                  <span className="tl-label">{s.tool}</span>
                  <span className="tl-time">
                    {s.status === 'waiting_permission' ? 'awaiting you' :
                     s.duration_ms != null ? (s.duration_ms / 1000).toFixed(1) + 's' : '…'}
                  </span>
                </div>
              ))}
            </div>
          </React.Fragment>
        )}
        {artifacts.length > 0 && (
          <React.Fragment>
            <div className="rail-section">Files produced</div>
            {artifacts.slice(0, 8).map((a, i) => (
              <div className="file-row" key={i} onClick={onOpenWorkspace}>
                <span className={'ext-badge' + (/pdf|pptx/.test(a.kind) ? ' hot' : '')}>{(a.kind || 'file').toUpperCase()}</span>
                <span className="file-name">{a.name}</span>
                <span className="file-size">{fmtBytes(a.size_bytes)}</span>
              </div>
            ))}
          </React.Fragment>
        )}
        <button className="rail-cta" onClick={onOpenWorkspace}>open Workspace →</button>
      </div>
    </div>
  );
}

/* ── Workspace view ────────────────────────────────────────────────────────── */

function WorkspaceView({ conv, wsFiles, wsMode, onRefresh, onSettings, artifacts }) {
  const [sel, setSel] = useState(null);
  const [preview, setPreview] = useState(null); // {kind, url|text}

  const files = useMemo(() => {
    const flat = [];
    const walk = (nodes, prefix) => (nodes || []).forEach(n => {
      if (n.children) walk(n.children, prefix + n.name + '/');
      else flat.push({ path: n.path || (prefix + n.name), name: n.name, size: n.size });
    });
    walk(wsFiles, '');
    return flat;
  }, [wsFiles]);

  useEffect(() => {
    if (!sel) { setPreview(null); return; }
    const ext = sel.path.split('.').pop().toLowerCase();
    const q = conv ? `?conv_id=${encodeURIComponent(conv)}` : '';
    let cancelled = false;
    if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) {
      fetchBlobURL(`/workspace/download/${encodeURIComponent(sel.path)}${q}`)
        .then(u => !cancelled && setPreview({ kind: 'img', url: u }))
        .catch(() => !cancelled && setPreview({ kind: 'err' }));
    } else if (['pdf', 'pptx', 'docx', 'xlsx', 'zip'].includes(ext)) {
      setPreview({ kind: 'bin' });
    } else {
      Auth.fetchJSON(`/workspace/files/${encodeURIComponent(sel.path)}${q}`)
        .then(d => !cancelled && setPreview({ kind: 'text', text: (d && d.content || '').slice(0, 20000) }))
        .catch(() => !cancelled && setPreview({ kind: 'err' }));
    }
    return () => { cancelled = true; };
  }, [sel, conv]);

  const download = (f) => {
    const q = conv ? `?conv_id=${encodeURIComponent(conv)}` : '';
    downloadBlob(`/workspace/download/${encodeURIComponent(f.path)}${q}`, f.name);
  };

  const fromMap = useMemo(() => {
    const m = {};
    (artifacts || []).forEach(a => { m[a.name] = a.meta && a.meta.prompt ? 'generated · ' + a.meta.prompt.slice(0, 40) : 'produced by agent'; });
    return m;
  }, [artifacts]);

  return (
    <div className="ws-view">
      <div className="ws-head">
        <span className="ws-title">Workspace</span>
        <span className="tag" style={{ marginTop: 6 }}>{(wsMode || 'cloud').toUpperCase()}</span>
        <span className="spacer" />
        <button className="chip" onClick={onRefresh}>↻ refresh</button>
        <button className="chip" onClick={onSettings}>settings</button>
      </div>
      <div className="ws-body">
        <div className="ws-list">
          <div className="mount-card">
            <Ic.folder />
            <span className="mount-path">{conv ? 'workspace / this conversation' : 'workspace / (no conversation selected)'}</span>
            <span className="mount-badge">{files.length} FILES</span>
            <span className="spacer" />
            <span className="dim" style={{ fontSize: 11 }}>files are isolated per conversation — the agent reads &amp; writes here</span>
          </div>
          <div className="ws-grid-head"><span>Name</span><span>Size</span><span></span></div>
          {files.map(f => (
            <div key={f.path} className={'ws-row' + (sel && sel.path === f.path ? ' sel' : '')} onClick={() => setSel(f)}>
              <span className="name">
                <span className="ext-badge">{(f.name.split('.').pop() || '').toUpperCase()}</span>
                <span style={{ minWidth: 0 }}>
                  <div className="fname">{f.path}</div>
                  {fromMap[f.name] && <div className="from">{fromMap[f.name]}</div>}
                </span>
              </span>
              <span className="cell">{f.size != null ? fmtBytes(f.size) : ''}</span>
              <span className="cell">
                <button className="mini-btn" onClick={e => { e.stopPropagation(); download(f); }}><Ic.dl /> get</button>
              </span>
            </div>
          ))}
          {!files.length && <div className="dim" style={{ padding: '30px 12px' }}>No files yet — attach files or run the agent and its outputs land here.</div>}
        </div>
        {sel && preview && (
          <div className="ws-preview">
            <div className="ws-preview-head">
              <span className="artifact-name">{sel.name}</span>
              <span className="spacer" />
              <button className="mini-btn" onClick={() => download(sel)}>download</button>
              <button className="x-btn" onClick={() => setSel(null)}>✕</button>
            </div>
            <div className="ws-preview-body">
              {preview.kind === 'img' && <img src={preview.url} alt={sel.name} />}
              {preview.kind === 'text' && <pre>{preview.text}</pre>}
              {preview.kind === 'bin' && <div className="dim" style={{ padding: 40, textAlign: 'center' }}>Binary file — use download to open in its native app.</div>}
              {preview.kind === 'err' && <div className="dim" style={{ padding: 40 }}>Could not preview.</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Admin view ────────────────────────────────────────────────────────────── */

function AdminView({ pushToast }) {
  const [tab, setTab] = useState('users');
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [costs, setCosts] = useState([]);
  const [days, setDays] = useState(30);
  const [nu, setNu] = useState({ username: '', display_name: '', password: '', is_admin: false });

  const loadUsers = () => Auth.fetchJSON('/admin/users').then(d => setUsers(d || []));
  useEffect(() => { loadUsers(); }, []);
  useEffect(() => { if (tab === 'usage') Auth.fetchJSON('/admin/stats').then(setStats); }, [tab]);
  useEffect(() => { if (tab === 'costs') Auth.fetchJSON(`/admin/costs?days=${days}`).then(d => setCosts(d || [])); }, [tab, days]);

  const createUser = async () => {
    if (!nu.username || !nu.password) return;
    const res = await fetch('/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...Auth.authHeaders() },
      body: JSON.stringify(nu),
    });
    if (res.ok) { pushToast(`User ${nu.username} created`); setNu({ username: '', display_name: '', password: '', is_admin: false }); loadUsers(); }
    else { const e = await res.json().catch(() => ({})); pushToast(e.detail || 'Create failed', true); }
  };

  const resetPw = async (u) => {
    const pw = prompt(`New password for ${u.username}:`);
    if (!pw) return;
    await fetch(`/admin/users/${u.id}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...Auth.authHeaders() },
      body: JSON.stringify({ new_password: pw }),
    });
    pushToast('Password reset');
  };

  const toggle = async (u) => {
    await fetch(`/admin/users/${u.id}/toggle`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...Auth.authHeaders() },
      body: JSON.stringify({ is_active: !u.is_active }),
    });
    loadUsers();
  };

  const totalCost = costs.reduce((s, r) => s + (+r.cost_usd || 0), 0);

  return (
    <div className="admin-view">
      <h1 className="admin-title">Admin</h1>
      <div className="admin-tabs">
        {['users', 'usage', 'costs'].map(t => (
          <button key={t} className={'admin-tab' + (tab === t ? ' active' : '')} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'users' && (
        <React.Fragment>
          <table className="admin-table">
            <thead><tr><th>Name</th><th>Username</th><th>Auth</th><th>Convs</th><th>Msgs</th><th>Status</th><th>Role</th><th>Actions</th></tr></thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id}>
                  <td className="strong">{u.display_name || u.username}</td>
                  <td className="mono">{u.username}</td>
                  <td className="mono">{u.auth_method}</td>
                  <td>{u.conv_count}</td><td>{u.msg_count}</td>
                  <td>{u.is_active ? <span className="pill-ok">ACTIVE</span> : <span className="pill-off">DISABLED</span>}</td>
                  <td>{u.is_admin ? <span className="mono" style={{ color: 'var(--red)', fontSize: 11 }}>admin</span> : <span className="dim">—</span>}</td>
                  <td style={{ display: 'flex', gap: 6 }}>
                    <button className="mini-btn" onClick={() => resetPw(u)}>reset pw</button>
                    <button className="mini-btn" onClick={() => toggle(u)}>{u.is_active ? 'disable' : 'enable'}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 24, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input className="admin-input" placeholder="Username" value={nu.username} onChange={e => setNu({ ...nu, username: e.target.value })} />
            <input className="admin-input" placeholder="Display name" value={nu.display_name} onChange={e => setNu({ ...nu, display_name: e.target.value })} />
            <input className="admin-input" placeholder="Password" type="password" value={nu.password} onChange={e => setNu({ ...nu, password: e.target.value })} />
            <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12.5, color: 'var(--ink2)' }}>
              <input type="checkbox" checked={nu.is_admin} onChange={e => setNu({ ...nu, is_admin: e.target.checked })} /> Admin
            </label>
            <button className="btn-new" style={{ padding: '8px 16px' }} onClick={createUser}>+ Create user</button>
          </div>
        </React.Fragment>
      )}

      {tab === 'usage' && stats && (
        <React.Fragment>
          <div className="stat-tiles">
            <div className="stat-tile"><div className="num">{stats.total_users}</div><div className="lbl">Users</div></div>
            <div className="stat-tile"><div className="num">{stats.total_conversations}</div><div className="lbl">Conversations</div></div>
            <div className="stat-tile"><div className="num">{stats.total_messages}</div><div className="lbl">Messages</div></div>
          </div>
          <table className="admin-table">
            <thead><tr><th>User</th><th>Username</th><th>Conversations</th><th>Messages</th></tr></thead>
            <tbody>
              {(stats.by_user || []).map((r, i) => (
                <tr key={i}>
                  <td className="strong">{r.display_name || r.username}</td>
                  <td className="mono">{r.username}</td>
                  <td>{r.convs}</td><td>{r.msgs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </React.Fragment>
      )}

      {tab === 'costs' && (
        <React.Fragment>
          <div style={{ display: 'flex', gap: 6, marginBottom: 16, alignItems: 'center' }}>
            <span className="dim" style={{ fontSize: 13 }}>Last</span>
            {[7, 30, 90].map(d => (
              <button key={d} className={'tier-chip' + (days === d ? ' on' : '')} onClick={() => setDays(d)}>{d}d</button>
            ))}
            <span className="spacer" />
            <span className="mono" style={{ fontSize: 12, color: 'var(--ok)' }}>total ${totalCost.toFixed(4)}</span>
          </div>
          <table className="admin-table">
            <thead><tr><th>User</th><th>Model</th><th>Calls</th><th>Input tok</th><th>Output tok</th><th>Cost (USD)</th></tr></thead>
            <tbody>
              {costs.map((r, i) => (
                <tr key={i}>
                  <td className="strong">{r.display_name || r.username}</td>
                  <td className="mono" style={{ fontSize: 11 }}>{r.model}</td>
                  <td>{r.calls}</td>
                  <td>{(+r.input_tokens).toLocaleString()}</td>
                  <td>{(+r.output_tokens).toLocaleString()}</td>
                  <td style={{ color: 'var(--ok)', fontWeight: 600 }}>${(+r.cost_usd).toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </React.Fragment>
      )}
    </div>
  );
}

/* ── Workspace settings modal ──────────────────────────────────────────────── */

function WsSettingsModal({ open, onClose, mode, customPath, onSave }) {
  const [m, setM] = useState(mode || 'cloud');
  const [p, setP] = useState(customPath || '');
  useEffect(() => { setM(mode || 'cloud'); setP(customPath || ''); }, [open, mode, customPath]);
  if (!open) return null;
  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ width: 460 }}>
        <div className="modal-head">
          <span className="modal-title">Workspace settings</span>
          <button className="x-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13, color: 'var(--ink2)', margin: '0 0 16px' }}>
            Each conversation gets its own isolated folder. Agent reads &amp; writes stay inside it.
          </p>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button className={'chip' + (m === 'cloud' ? ' on' : '')} style={{ flex: 1, justifyContent: 'center', padding: '10px 0' }}
                    onClick={() => setM('cloud')}>Cloud (server-managed)</button>
            <button className={'chip' + (m === 'local' ? ' on' : '')} style={{ flex: 1, justifyContent: 'center', padding: '10px 0' }}
                    onClick={() => setM('local')}>Local (custom path)</button>
          </div>
          {m === 'local' && (
            <input className="admin-input" style={{ width: '100%', marginBottom: 16 }}
                   placeholder="e.g. C:\\Users\\you\\rdi-workspace or /home/you/rdi-workspace"
                   value={p} onChange={e => setP(e.target.value)} />
          )}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button className="mini-btn" onClick={onClose}>Cancel</button>
            <button className="btn-new" style={{ padding: '7px 16px' }} onClick={() => { onSave(m, p); onClose(); }}>Save</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Image preview modal ───────────────────────────────────────────────────── */

function ImageModal({ img, onClose, onEdit, onVary }) {
  if (!img) return null;
  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <span className="modal-title mono">{img.name}</span>
          <button className="mini-btn" onClick={onEdit}>edit</button>
          <button className="mini-btn" onClick={onVary}>vary ×4</button>
          <button className="mini-btn" onClick={() => {
            const a = document.createElement('a');
            a.href = `data:image/png;base64,${img.content}`; a.download = img.name; a.click();
          }}>download</button>
          <button className="x-btn" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ display: 'flex', justifyContent: 'center' }}>
          <img src={`data:image/png;base64,${img.content}`} alt={img.name} style={{ maxWidth: '100%', borderRadius: 8 }} />
        </div>
      </div>
    </div>
  );
}

/* ── App shell ─────────────────────────────────────────────────────────────── */

function App() {
  const [authed, setAuthed] = useState(Auth.isLoggedIn());
  const [user, setUser] = useState(Auth.getUser() || {});
  const [theme, setTheme] = useState(localStorage.getItem('rdi_theme') || 'light');
  const [view, setView] = useState('chat');
  const [agentMode, setAgentMode] = useState(false);
  const [convs, setConvs] = useState([]);
  const [convId, setConvId] = useState(null);
  const [convTitle, setConvTitle] = useState('');
  const [messages, setMessages] = useState([]);
  const [streamText, setStreamText] = useState('');
  const [streamRun, setStreamRun] = useState(null);
  const [activity, setActivity] = useState([]);
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState(localStorage.getItem('rdi_model') || 'gpt-4.1-global');
  const [modelOpen, setModelOpen] = useState(false);
  const [permission, setPermission] = useState(null);
  const [autoAllow, setAutoAllow] = useState(false);
  const [guard, setGuard] = useState(null);
  const [fallback, setFallback] = useState(null);
  const [conn, setConn] = useState('connecting');
  const [connAttempt, setConnAttempt] = useState(0);
  const [attachments, setAttachments] = useState([]);
  const [crossChat, setCrossChat] = useState(false);
  const [wsFiles, setWsFiles] = useState([]);
  const [wsMode, setWsMode] = useState('cloud');
  const [wsCustomPath, setWsCustomPath] = useState('');
  const [wsSettingsOpen, setWsSettingsOpen] = useState(false);
  const [artifacts, setArtifacts] = useState([]);
  const [railOpen, setRailOpen] = useState(true);
  const [toasts, setToasts] = useState([]);
  const [imgModal, setImgModal] = useState(null);
  const [convSearch, setConvSearch] = useState('');
  const [, setCatalogVersion] = useState(0);

  const streamRef = useRef('');
  const runRef = useRef(null);
  const activityRef = useRef([]);
  const pendingRequestRef = useRef(null);
  const loadTargetRef = useRef(null);
  const busyRef = useRef(false);
  const modelRef = useRef(model);
  const convRef = useRef(convId);
  useEffect(() => { modelRef.current = model; }, [model]);
  useEffect(() => { convRef.current = convId; }, [convId]);

  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('rdi_theme', theme); }, [theme]);
  useEffect(() => { localStorage.setItem('rdi_model', model); }, [model]);

  const pushToast = useCallback((text, err) => {
    const id = ++_toastId;
    setToasts(ts => [...ts, { id, text, err }]);
    setTimeout(() => setToasts(ts => ts.filter(t => t.id !== id)), 4200);
  }, []);

  useEffect(() => {
    if (!authed) return;
    Auth.fetchJSON('/models/catalog')
      .then(items => {
        RUNTIME_MODEL_MAP = {};
        (items || []).forEach(m => { RUNTIME_MODEL_MAP[m.id] = m; });
        setCatalogVersion(v => v + 1);
        const selected = RUNTIME_MODEL_MAP[modelRef.current];
        if (selected && selected.available === false) {
          const fallback = (items || []).find(m => m.available && m.capabilities && m.capabilities.tools)
            || (items || []).find(m => m.available);
          if (fallback) {
            setModel(fallback.id);
            modelRef.current = fallback.id;
          }
        }
      })
      .catch(() => {});
  }, [authed]);

  /* ── WS wiring ── */
  useEffect(() => {
    if (!authed) return;

    RdiWS.on('init', d => {
      setUser(u => ({ ...u, ...d.user }));
      setConvs(d.conversations || []);
      setWsMode(d.user.workspace_mode || 'cloud');
      setWsCustomPath(d.user.workspace_custom_path || '');
    });
    RdiWS.on('conversations', d => setConvs(d.conversations || []));
    RdiWS.on('conversation_created', d => {
      // The creation acknowledgement may arrive after the user clicked New chat.
      if (!d.request_id || d.request_id !== pendingRequestRef.current) return;
      convRef.current = d.id;
      setConvId(d.id); setConvTitle(d.conversation.title);
      RdiWS.setActiveConversation(d.id, 0);
      setConvs(cs => [d.conversation, ...cs.filter(c => c.id !== d.id)]);
    });
    RdiWS.on('conversation_loaded', d => {
      if (loadTargetRef.current !== d.conversation.id) return;
      loadTargetRef.current = null;
      convRef.current = d.conversation.id;
      setConvId(d.conversation.id);
      setConvTitle(d.conversation.title);
      setModel(d.conversation.model || modelRef.current);
      setCrossChat(!!d.cross_chat_reference);
      setMessages((d.messages || []).map(m => ({
        role: m.role, content: m.content, attachments: m.attachments || [],
      })));
      streamRef.current = d.partial_text || '';
      setStreamText(streamRef.current);
      activityRef.current = d.activity_log || [];
      setActivity(activityRef.current);
      runRef.current = d.running && d.last_run ? { steps: d.last_run.steps || [] } : null;
      setStreamRun(runRef.current);
      busyRef.current = !!d.running;
      setBusy(busyRef.current);
      RdiWS.setActiveConversation(d.conversation.id, d.current_seq || 0);
      RdiWS.send({ type: 'get_artifacts', conversation_id: d.conversation.id });
      RdiWS.send({ type: 'get_workspace' });
    });
    RdiWS.on('conversation_deleted', d => {
      setConvs(cs => cs.filter(c => c.id !== d.id));
      if (convRef.current === d.id) {
        convRef.current = null; RdiWS.setActiveConversation(null, 0);
        setConvId(null); setMessages([]); setStreamText(''); setStreamRun(null);
        activityRef.current = []; setActivity([]); busyRef.current = false; setBusy(false);
      }
    });
    RdiWS.on('conversation_renamed', d => {
      setConvs(cs => cs.map(c => c.id === d.id ? { ...c, title: d.title } : c));
      if (convRef.current === d.id) setConvTitle(d.title);
    });

    RdiWS.on('token', d => {
      streamRef.current += d.text;
      setStreamText(streamRef.current);
      busyRef.current = true;
      setBusy(true);
    });
    RdiWS.on('done', () => {
      finalizeStream();
      busyRef.current = false;
      pendingRequestRef.current = null;
      setBusy(false);
      RdiWS.send({ type: 'list_conversations' });
    });
    RdiWS.on('error', d => {
      if (d.request_id && d.request_id !== pendingRequestRef.current) return;
      if (streamRef.current || runRef.current) finalizeStream();
      busyRef.current = false;
      pendingRequestRef.current = null;
      setBusy(false);
      pushToast(d.message || 'Something went wrong', true);
    });

    RdiWS.on('run_started', d => {
      runRef.current = { run_id: d.run_id, steps: [] };
      setStreamRun(runRef.current);
    });
    RdiWS.on('run_step', d => {
      if (d.final && !busyRef.current) return; // cancelled run already finalized
      runRef.current = { ...(runRef.current || {}), run_id: d.run_id, steps: d.steps || [], final: d.final };
      setStreamRun(runRef.current);
      if (d.final) setPermission(null);
    });
    RdiWS.on('model_fallback', d => {
      setFallback(d);
      pushToast(`${modelName(d.requested)} is being used as a specialist; orchestration continues on ${modelName(d.fallback)}`);
    });
    RdiWS.on('auto_agent_started', d => {
      pushToast(d.reason || 'Using tools automatically for this request');
    });
    RdiWS.on('permission', d => setPermission(d));
    RdiWS.on('permission_timeout', d => {
      setPermission(null);
      pushToast(d.message || 'Permission expired; tool not executed', true);
    });
    RdiWS.on('permission_auto', d => pushToast(`auto-approved read-only: ${d.tool}`));
    RdiWS.on('auto_allow_set', d => setAutoAllow(!!d.enabled));

    RdiWS.on('request_rejected', d => pushToast(d.message || 'Request rejected', true));
    RdiWS.on('tool_result', () => {});
    RdiWS.on('activity', d => {
      activityRef.current = [...activityRef.current, { action: d.action || 'Working…', icon: d.icon || '·' }].slice(-16);
      setActivity(activityRef.current);
    });
    RdiWS.on('activity_done', () => {
      busyRef.current = false;
      pendingRequestRef.current = null;
      setBusy(false);
    });
    RdiWS.on('cancelled', d => {
      if (streamRef.current || runRef.current) finalizeStream();
      busyRef.current = false;
      pendingRequestRef.current = null;
      setBusy(false);
      setPermission(null);
      pushToast(d.message || 'Run stopped');
    });
    RdiWS.on('workspace', d => {
      const responseConv = d.conversation_id || d.conv_id;
      if (responseConv && responseConv !== convRef.current) return;
      setWsFiles(d.files || []); if (d.workspace_mode) setWsMode(d.workspace_mode);
    });
    RdiWS.on('artifacts', d => {
      if (d.conv_id !== convRef.current) return;
      setArtifacts(d.artifacts || []);
    });
    RdiWS.on('workspace_settings_updated', d => {
      setWsMode(d.mode); setWsCustomPath(d.custom_path || '');
      pushToast('Workspace settings saved');
    });
    RdiWS.on('cross_chat_reference_set', d => setCrossChat(!!d.enabled));

    RdiWS.on('image_result', d => {
      const name = d.filename || `generated_${Date.now()}.png`;
      if (d.base64) {
        setMessages(ms => [...ms, {
          role: 'assistant',
          content: d.prompt ? `Generated for: *${d.prompt}*` : '',
          attachments: [{ name, type: 'image/png', content: d.base64 }],
          meta: modelName(d.model || modelRef.current),
        }]);
      }
      RdiWS.send({ type: 'get_workspace' });
      if (convRef.current) RdiWS.send({ type: 'get_artifacts', conversation_id: convRef.current });
    });

    RdiWS.on('audio_result', d => {
      try { new Audio(`data:audio/mp3;base64,${d.base64}`).play(); } catch (e) {}
    });

    RdiWS.on('resume_ok', d => {
      if (typeof d.snapshot === 'string') {
        streamRef.current = d.snapshot;
        setStreamText(d.snapshot);
        RdiWS.setActiveConversation(convRef.current, d.current_seq || 0);
      }
      if (d.reload_required && convRef.current) {
        // Completed message is in PostgreSQL, not in the finite replay buffer.
        loadTargetRef.current = convRef.current;
        RdiWS.setActiveConversation(convRef.current, d.current_seq || 0);
        RdiWS.send({ type: 'load_conversation', conversation_id: convRef.current });
      }
      if (d.replayed > 0) pushToast(`Reconnected — resumed stream (${d.replayed} events replayed)`);
      if (d.running) { busyRef.current = true; setBusy(true); }
    });

    RdiWS.connect((status, attempt) => {
      setConn(status);
      setConnAttempt(attempt || 0);
      if (status === 'reconnected') {
        setTimeout(() => setConn(s => (s === 'reconnected' ? 'connected' : s)), 3500);
        if (RdiWS.queuedCount() === 0) pushToast('Reconnected');
      }
      if (status === 'unauthorized') { Auth.clear(); window.location.reload(); }
    });

    return () => RdiWS.disconnect();
  }, [authed]);

  const finalizeStream = () => {
    const text = streamRef.current;
    const run = runRef.current;
    if (text || run) {
      setMessages(ms => [...ms, {
        role: 'assistant', content: text, run, activity: activityRef.current,
        meta: modelName(modelRef.current),
      }]);
    }
    streamRef.current = ''; setStreamText('');
    runRef.current = null; setStreamRun(null);
    activityRef.current = []; setActivity([]);
    setPermission(null);
  };

  /* ── Keyboard: ⌘K ── */
  useEffect(() => {
    const h = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setModelOpen(o => !o); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  /* ── Actions ── */
  const resetActiveView = () => {
    const oldId = convRef.current;
    const oldRequest = pendingRequestRef.current;
    if (busyRef.current) {
      RdiWS.dropPending(oldRequest);
      RdiWS.send({ type: 'stop', conversation_id: oldId, request_id: oldRequest });
    }
    pendingRequestRef.current = null;
    loadTargetRef.current = null;
    busyRef.current = false;
    convRef.current = null;
    RdiWS.setActiveConversation(null, 0);
    setConvId(null); setConvTitle(''); setMessages([]);
    streamRef.current = ''; setStreamText('');
    runRef.current = null; setStreamRun(null);
    activityRef.current = []; setActivity([]);
    setBusy(false); setPermission(null); setArtifacts([]);
    setCrossChat(false); setFallback(null);
  };

  const newConversation = () => {
    resetActiveView();
    setView('chat');
  };

  const openConv = (id) => {
    if (id === convRef.current) return;
    resetActiveView();
    loadTargetRef.current = id;
    convRef.current = id;
    RdiWS.setActiveConversation(id, 0);
    setConvId(id);
    setView('chat');
    RdiWS.send({ type: 'load_conversation', conversation_id: id });
  };

  const deleteConv = (id) => {
    if (!confirm('Delete this conversation and its files?')) return;
    RdiWS.send({ type: 'delete_conversation', conversation_id: id });
  };

  const renameConv = (c) => {
    const t = prompt('Rename conversation:', c.title);
    if (t && t.trim()) RdiWS.send({ type: 'rename_conversation', conversation_id: c.id, title: t.trim() });
  };

  const uploadFile = useCallback((file, existingKey) => {
    const key = existingKey || `${file.name}-${Date.now()}`;
    setAttachments(list => {
      const rest = list.filter(a => a.key !== key);
      return [...rest, { key, name: file.name, file, status: 'uploading' }];
    });
    const form = new FormData();
    form.append('file', file);
    if (convRef.current) form.append('conversation_id', convRef.current);
    fetch('/files/upload', { method: 'POST', headers: Auth.authHeaders(), body: form })
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => setAttachments(list => list.map(a => a.key === key
        ? { ...a, status: 'done', payload: {
            id: d.attachment_id || d.id,
            attachment_id: d.attachment_id || d.id,
            name: d.filename,
            type: d.content_type,
            content_type: d.content_type,
            size: d.size,
          } } : a)))
      .catch(() => setAttachments(list => list.map(a => a.key === key ? { ...a, status: 'failed' } : a)));
  }, []);

  const sendMessage = (text, atts) => {
    const payloadAtts = atts.map(a => a.payload).filter(Boolean);
    const imgMode = isImageModel(model);
    if (busyRef.current) return;
    const requestId = 'turn-' + Date.now() + '-' + Math.random().toString(36).slice(2);
    pendingRequestRef.current = requestId;
    setMessages(ms => [...ms, { role: 'user', content: text, attachments: payloadAtts }]);
    busyRef.current = true;
    setBusy(true);
    streamRef.current = ''; setStreamText('');
    runRef.current = null; setStreamRun(null);
    activityRef.current = []; setActivity([]);
    setFallback(null);
    if (imgMode) {
      RdiWS.send({ type: 'generate_image', request_id: requestId,
                   prompt: text, model, conversation_id: convRef.current, attachments: payloadAtts });
    } else {
      RdiWS.send({
        type: 'chat', request_id: requestId, message: text, model, conversation_id: convRef.current,
        agent_mode: agentMode && !imgMode, auto_agent: true, attachments: payloadAtts,
      });
    }
    if (!RdiWS.isConnected()) pushToast('Offline — message queued, will send on reconnect');
  };

  const decidePermission = (decision, always = false) => {
    if (!permission) return;
    RdiWS.send({ type: 'permission', request_id: permission.request_id,
                 decision, always: !!always });
    if (always) pushToast(`${permission.tool} auto-approved for this active conversation`);
    setPermission(null);
  };

  const setAutoAllowBoth = (v) => {
    setAutoAllow(v);
    RdiWS.send({ type: 'set_auto_allow', enabled: v });
  };

  const pickModel = (id) => {
    setModel(id);
    setModelOpen(false);
    RdiWS.send({ type: 'set_model', model: id });
    setGuard(agentMode && isNoToolsModel(id) && !isImageModel(id) ? id : null);
  };

  const exportConv = (fmt) => {
    if (!convId) return;
    if (fmt === 'pdf') {
      // Browser print preserves visible Mermaid SVG, charts, code and tables.
      // The user chooses Save as PDF; server remains an API fallback.
      window.print();
      return;
    }
    downloadBlob(`/conversations/${convId}/export?format=${fmt}`, `${convTitle || 'conversation'}.${fmt}`);
  };

  const imageAction = (img, action) => {
    if (!action) { setImgModal(img); return; }
    if (action === 'edit') {
      const change = prompt('Describe the image edit:');
      if (change) {
        setBusy(true);
        RdiWS.send({
          type: 'edit_image',
          conversation_id: convId,
          source_name: img.name,
          image_base64: img.content,
          prompt: change,
          model: 'gpt-image-1-global',
          count: 1,
        });
      }
    } else if (action === 'vary') {
      setBusy(true);
      RdiWS.send({
        type: 'edit_image',
        conversation_id: convId,
        source_name: img.name,
        image_base64: img.content,
        prompt: 'Create a faithful variation of this image: preserve the subject, intent and key visual identity while exploring a meaningfully different composition.',
        model: 'gpt-image-1-global',
        count: 4,
      });
    }
    setImgModal(null);
  };

  if (!authed) return <Login onAuthed={() => { setUser(Auth.getUser() || {}); setAuthed(true); }} />;

  const filteredConvs = convs.filter(c => !convSearch || (c.title || '').toLowerCase().includes(convSearch.toLowerCase()));
  const hasRun = streamRun || (messages.length && messages[messages.length - 1].run);
  const lastRun = streamRun || (hasRun ? messages[messages.length - 1].run : null);

  const composer = (
    <Composer
      conv={convId} agentMode={agentMode} model={model} busy={busy}
      disabled={false}
      onOpenModel={() => setModelOpen(true)}
      onSend={sendMessage}
      onStop={() => RdiWS.send({ type: 'stop', conversation_id: convRef.current,
                                     request_id: pendingRequestRef.current })}
      attachments={attachments} setAttachments={setAttachments} uploadFile={uploadFile}
      guard={guard}
      onGuardDismiss={() => setGuard(null)}
      onGuardChat={() => { setAgentMode(false); setGuard(null); }}
      permission={permission} onPermission={decidePermission}
      autoAllow={autoAllow} onAutoAllow={setAutoAllowBoth}
    />
  );

  return (
    <React.Fragment>
      <div className="red-hairline" />
      <div className="app-frame">
        {/* Ink rail */}
        <div className="rail">
          <div className="rail-logo" title="RDI AI">R</div>
          <button className={'rail-btn' + (view === 'chat' && !agentMode ? ' active' : '')} title="Chat"
                  onClick={() => { setView('chat'); setAgentMode(false); }}><Ic.chat /></button>
          <button className={'rail-btn' + (view === 'chat' && agentMode ? ' active' : '')} title="Agent"
                  onClick={() => { setView('chat'); setAgentMode(true); }}><Ic.agent /></button>
          <button className={'rail-btn' + (view === 'workspace' ? ' active' : '')} title="Workspace"
                  onClick={() => { setView('workspace'); RdiWS.send({ type: 'get_workspace' }); }}><Ic.folder /></button>
          {user.is_admin && (
            <button className={'rail-btn' + (view === 'admin' ? ' active' : '')} title="Admin"
                    onClick={() => setView('admin')}><Ic.admin /></button>
          )}
          <div className="rail-spacer" />
          <button className="rail-btn" title="Toggle theme" onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')}><Ic.sun /></button>
          <button className="rail-avatar" title={`${user.display_name} · sign out`}
                  onClick={() => { if (confirm('Sign out?')) { RdiWS.disconnect(); Auth.clear(); window.location.reload(); } }}>
            {(user.display_name || 'U').split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase()}
          </button>
        </div>

        {/* Conversations panel */}
        {view === 'chat' && (
          <div className="convs">
            <div className="convs-head">
              <button className="btn-new" onClick={newConversation}><Ic.plus /> New conversation</button>
              <input className="conv-search" placeholder="Search conversations" value={convSearch}
                     onChange={e => setConvSearch(e.target.value)} />
            </div>
            <div className="convs-list">
              {groupByDate(filteredConvs).map(([label, items]) => (
                <React.Fragment key={label}>
                  <div className="conv-group">{label}</div>
                  {items.map(c => (
                    <div key={c.id} className={'conv-item' + (c.id === convId ? ' active' : '')} onClick={() => openConv(c.id)}>
                      <span className="conv-title">{c.title}</span>
                      <span className="conv-meta">
                        <span className="conv-time">{relTime(c.updated_at)}</span>
                        <span className="conv-time dim">{modelName(c.model).split(' ')[0]}</span>
                      </span>
                      <span className="conv-actions">
                        <button className="conv-action-btn" title="Rename" onClick={e => { e.stopPropagation(); renameConv(c); }}>✎</button>
                        <button className="conv-action-btn" title="Delete" onClick={e => { e.stopPropagation(); deleteConv(c.id); }}>✕</button>
                      </span>
                    </div>
                  ))}
                </React.Fragment>
              ))}
              {!filteredConvs.length && <div className="dim" style={{ padding: 20, fontSize: 12.5 }}>No conversations yet.</div>}
            </div>
            <div className="convs-foot" onClick={() => { setView('workspace'); RdiWS.send({ type: 'get_workspace' }); }}>
              <Ic.folder />
              <span style={{ fontSize: 12, color: 'var(--ink2)', flex: 1 }}>Workspace</span>
              <span className="tag">{wsMode.toUpperCase()}</span>
            </div>
          </div>
        )}

        {/* Main column */}
        <div className="main-col">
          {view === 'chat' && (
            <React.Fragment>
              <div className="topbar">
                <div className="mode-switch">
                  <button className={'mode-btn' + (!agentMode ? ' active' : '')} onClick={() => setAgentMode(false)}>Chat</button>
                  <button className={'mode-btn' + (agentMode ? ' active' : '')} onClick={() => setAgentMode(true)}>Agent</button>
                </div>
                <span className="topbar-title">{convTitle || (agentMode ? 'Agent' : 'New conversation')}</span>
                {agentMode && convId && <span className="tag agent">AGENT</span>}
                <span className="spacer" />
                {convId && (
                  <React.Fragment>
                    <button className={'chip' + (crossChat ? ' on' : '')}
                            title="When on, the agent can reference your other conversations"
                            onClick={() => RdiWS.send({ type: 'set_cross_chat_reference', enabled: !crossChat })}>
                      <Ic.link /> {crossChat ? 'Cross-chat on' : 'Cross-chat'}
                    </button>
                    <button className="chip" onClick={() => exportConv('pdf')}><Ic.dl /> PDF</button>
                    <button className="chip" onClick={() => exportConv('docx')}><Ic.dl /> DOCX</button>
                    <button className="chip" title="Lossless conversation Markdown source" onClick={() => exportConv('md')}><Ic.dl /> Markdown</button>
                  </React.Fragment>
                )}
                {agentMode && (
                  <button className="chip" onClick={() => setRailOpen(o => !o)}><Ic.cols /> Run</button>
                )}
                <span className={'conn-dot' + (conn === 'connected' || conn === 'reconnected' ? '' : ' bad')}
                      title={conn} />
              </div>

              {(conn === 'reconnecting' || conn === 'disconnected') && (
                <div className="conn-banner">
                  <span className="sq warn" />
                  <span><strong>Connection lost</strong> — reconnecting{connAttempt > 1 ? ` (attempt ${connAttempt})` : ''}…</span>
                  <span className="mono-note">
                    {RdiWS.queuedCount() > 0 ? `${RdiWS.queuedCount()} message(s) queued · ` : ''}run state saved · nothing is lost
                  </span>
                </div>
              )}
              {conn === 'reconnected' && (
                <div className="conn-banner ok">
                  <span className="sq ok" />
                  <span><strong>Reconnected</strong> — stream resumed from where it stopped.</span>
                </div>
              )}
              {fallback && (
                <div className="conn-banner">
                  <span className="sq warn" />
                  <span><strong>{modelName(fallback.requested)}</strong> has no tool support — this run continues on <strong>{modelName(fallback.fallback)}</strong>.</span>
                  <span className="spacer" />
                  <button className="guard-btn" onClick={() => setFallback(null)}>ok</button>
                </div>
              )}

              <ChatView
                conv={convId} messages={messages} streamText={streamText} streamRun={streamRun}
                busy={busy} activity={activity} user={user} agentMode={agentMode} setAgentMode={setAgentMode}
                model={model} connState={conn}
                recent={convs} onOpenConv={openConv}
                onSuggestion={(s) => sendMessage(s, [])}
                onImageClick={imageAction}
                permission={permission} onPermission={decidePermission}
                composer={composer}
              />
            </React.Fragment>
          )}

          {view === 'workspace' && (
            <WorkspaceView conv={convId} wsFiles={wsFiles} wsMode={wsMode} artifacts={artifacts}
                           onRefresh={() => RdiWS.send({ type: 'get_workspace' })}
                           onSettings={() => setWsSettingsOpen(true)} />
          )}
          {view === 'admin' && user.is_admin && <AdminView pushToast={pushToast} />}
        </div>

        {/* Run rail */}
        {view === 'chat' && agentMode && railOpen && (convId || streamRun) && (
          <RunRail run={lastRun} artifacts={artifacts} model={model}
                   onClose={() => setRailOpen(false)}
                   onOpenWorkspace={() => { setView('workspace'); RdiWS.send({ type: 'get_workspace' }); }} />
        )}
      </div>

      <ModelPalette open={modelOpen} onClose={() => setModelOpen(false)} current={model}
                    onPick={pickModel} agentMode={agentMode} />
      <WsSettingsModal open={wsSettingsOpen} onClose={() => setWsSettingsOpen(false)}
                       mode={wsMode} customPath={wsCustomPath}
                       onSave={(m, p) => RdiWS.send({ type: 'set_workspace_settings', mode: m, custom_path: p })} />
      <ImageModal img={imgModal} onClose={() => setImgModal(null)}
                  onEdit={() => imageAction(imgModal, 'edit')} onVary={() => imageAction(imgModal, 'vary')} />
      <Toasts toasts={toasts} />
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
