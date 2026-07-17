/* Auth utilities — JWT storage, SSO MSAL flow (plain JS, no JSX) */

const Auth = (() => {
  const TOKEN_KEY = 'rdi_jwt';
  const USER_KEY  = 'rdi_user';

  function save(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
    } catch { return null; }
  }

  function _b64urlDecode(s) {
    // JWT segments are base64URL (-, _) and unpadded — atob needs base64.
    s = s.replace(/-/g, '+').replace(/_/g, '/');
    while (s.length % 4) s += '=';
    return atob(s);
  }

  function isLoggedIn() {
    const token = getToken();
    if (!token) return false;
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return false;
      const payload = JSON.parse(_b64urlDecode(parts[1]));
      return payload.exp > Date.now() / 1000;
    } catch { return false; }
  }

  async function loginPassword(username, password) {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    save(data.access_token, data.user);
    return data.user;
  }

  async function getSSOConfig() {
    try {
      const res = await fetch('/auth/sso-config');
      return await res.json();
    } catch { return { enabled: false }; }
  }

  async function loginSSO() {
    const cfg = await getSSOConfig();
    if (!cfg.enabled) throw new Error('SSO not configured');

    // msal is loaded via CDN; if undefined the CDN script was blocked
    if (typeof msal === 'undefined') {
      throw new Error(
        'Microsoft login library failed to load. ' +
        'Please check your network connection or ask IT to whitelist cdn.jsdelivr.net.'
      );
    }

    const msalConfig = {
      auth: {
        clientId: cfg.client_id,
        authority: `https://login.microsoftonline.com/${cfg.tenant_id}`,
        redirectUri: window.location.origin,
        postLogoutRedirectUri: window.location.origin + '/login',
        navigateToLoginRequestUrl: false,
      },
      cache: {
        cacheLocation: 'localStorage',
        storeAuthStateInCookie: false,
      },
      system: {
        loggerOptions: {
          loggerCallback: (level, message, containsPii) => {
            if (containsPii) return;
            if (level === 0) console.error('[MSAL]', message);
          },
        },
      },
    };

    const msalApp = new msal.PublicClientApplication(msalConfig);
    await msalApp.initialize();

    // Use team scopes from config + standard Azure AD scopes
    const scopes = cfg.scopes && cfg.scopes.length
      ? cfg.scopes
      : ['openid', 'profile', 'email', 'User.Read', 'User.Read.All',
         'Group.Read.All', 'GroupMember.Read.All', 'offline_access'];

    const result = await msalApp.loginPopup({ scopes });
    const idToken = result.idToken;

    const res = await fetch('/auth/sso', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'SSO login failed');
    }

    const data = await res.json();
    save(data.access_token, data.user);
    return data.user;
  }

  function authHeaders() {
    const token = getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function fetchJSON(url, opts = {}) {
    const res = await fetch(url, {
      ...opts,
      headers: { ...authHeaders(), ...(opts.headers || {}) },
    });
    if (res.status === 401) {
      clear();
      window.location.reload();
      return null;
    }
    return res.json();
  }

  return { save, clear, getToken, getUser, isLoggedIn, loginPassword,
           loginSSO, getSSOConfig, authHeaders, fetchJSON };
})();
