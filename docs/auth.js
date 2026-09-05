/* GitHub OAuth authentication for Room Sync.
 *
 * ALL page content is gated behind authentication. The flow:
 * 1. Page loads with content hidden, sign-in prompt shown
 * 2. User clicks "Sign in with GitHub"
 * 3. Redirect to GitHub OAuth with the OAuth App's client ID
 * 4. GitHub redirects to Cloudflare Worker with authorization code
 * 5. Worker exchanges code for token (client secret stays server-side)
 * 6. Worker redirects back here with token in the URL fragment hash
 * 7. Token stored in sessionStorage (cleared on tab close)
 * 8. Org membership verified — only then is content revealed and data loaded
 *
 * No data is fetched and no room information is displayed until the user
 * proves they are a member of the Enterprise-AV GitHub organization.
 */

// Configuration — update these after creating the OAuth App and Worker
const OAUTH_CLIENT_ID = 'Ov23lin9PJWWmipdJ4kS';
const OAUTH_WORKER_URL = 'https://room-sync-oauth.abarquezj.workers.dev';
const GITHUB_ORG = 'Enterprise-AV';
const REPO_OWNER = 'Enterprise-AV';
const REPO_NAME = 'room-sync';

// Auth state flag — set to true only after org membership is verified.
// app.js checks this before loading any data.
let authVerified = false;

function getToken() {
  return sessionStorage.getItem('github_token');
}

function setToken(token) {
  sessionStorage.setItem('github_token', token);
}

function clearToken() {
  sessionStorage.removeItem('github_token');
  sessionStorage.removeItem('github_user');
}

function isAuthenticated() {
  return authVerified && !!getToken();
}

function getUser() {
  return sessionStorage.getItem('github_user');
}

// Gate: hide page content, show sign-in prompt
function showAuthGate() {
  const content = document.getElementById('gated-content');
  const gate = document.getElementById('auth-gate');
  if (content) content.style.display = 'none';
  if (gate) gate.style.display = 'block';
}

// Reveal page content after successful auth
function showContent() {
  const content = document.getElementById('gated-content');
  const gate = document.getElementById('auth-gate');
  if (content) content.style.display = 'block';
  if (gate) gate.style.display = 'none';
}

// Check for token in URL hash on page load (returned from OAuth callback)
(function checkHashToken() {
  // Always start gated
  showAuthGate();

  const hash = window.location.hash;
  if (hash.startsWith('#token=')) {
    const token = hash.substring(7);
    setToken(token);
    // Clean the URL
    history.replaceState(null, '', window.location.pathname + window.location.search);
    // Verify org membership
    verifyMembership(token);
  } else if (getToken()) {
    // Re-verify on every page load (token could be revoked)
    verifyMembership(getToken());
  }
})();

async function verifyMembership(token) {
  try {
    // Get the authenticated user
    const userResp = await fetch('https://api.github.com/user', {
      headers: { 'Authorization': `token ${token}` }
    });
    if (!userResp.ok) {
      clearToken();
      authVerified = false;
      showAuthGate();
      return;
    }
    const user = await userResp.json();
    sessionStorage.setItem('github_user', user.login);

    // Verify org membership
    const orgResp = await fetch(`https://api.github.com/orgs/${GITHUB_ORG}/members/${user.login}`, {
      headers: { 'Authorization': `token ${token}` }
    });
    if (orgResp.status !== 204) {
      clearToken();
      authVerified = false;
      showAuthGate();
      const gate = document.getElementById('auth-gate');
      if (gate) {
        gate.innerHTML = `
          <div style="text-align:center; padding:80px 20px;">
            <h2 style="color:#c0392b; margin-bottom:16px;">Access Denied</h2>
            <p>You must be a member of the <strong>${GITHUB_ORG}</strong> organization to access this tool.</p>
            <p style="color:#777; margin-top:24px;">Signed in as <strong>${user.login}</strong></p>
            <button class="btn btn-outline" onclick="clearToken(); window.location.reload();" style="margin-top:16px;">
              Try a different account
            </button>
          </div>`;
      }
      return;
    }

    // Membership verified
    authVerified = true;
    updateAuthUI();
    showContent();

    // Now that auth is confirmed, trigger data loading in app.js
    if (typeof onAuthReady === 'function') {
      onAuthReady();
    }
  } catch (e) {
    console.error('Auth verification failed:', e);
    clearToken();
    authVerified = false;
    showAuthGate();
  }
}

function updateAuthUI() {
  const btn = document.getElementById('auth-btn');
  if (!btn) return;

  if (isAuthenticated()) {
    const user = getUser();
    btn.textContent = user ? `Signed in as ${user}` : 'Signed in';
    btn.classList.add('signed-in');
  } else {
    btn.textContent = 'Sign in with GitHub';
    btn.classList.remove('signed-in');
  }
}

function toggleAuth() {
  if (isAuthenticated()) {
    if (confirm('Sign out?')) {
      clearToken();
      authVerified = false;
      updateAuthUI();
      window.location.reload();
    }
  } else {
    startOAuth();
  }
}

function startOAuth() {
  if (!OAUTH_CLIENT_ID || !OAUTH_WORKER_URL) {
    alert('OAuth is not configured yet. Set OAUTH_CLIENT_ID and OAUTH_WORKER_URL in auth.js after creating the GitHub OAuth App and Cloudflare Worker.');
    return;
  }
  const redirectUri = encodeURIComponent(OAUTH_WORKER_URL + '/callback');
  const scope = encodeURIComponent('read:org repo');
  window.location.href = `https://github.com/login/oauth/authorize?client_id=${OAUTH_CLIENT_ID}&scope=${scope}&redirect_uri=${redirectUri}`;
}

// Dispatch a GitHub Actions workflow
async function dispatchWorkflow(action, payload) {
  const token = getToken();
  if (!token) {
    alert('Please sign in with GitHub first.');
    return false;
  }

  const resp = await fetch(
    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/apply-changes.yml/dispatches`,
    {
      method: 'POST',
      headers: {
        'Authorization': `token ${token}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ref: 'main',
        inputs: {
          action: action,
          payload: JSON.stringify(payload),
        },
      }),
    }
  );

  if (resp.status === 204) {
    return true;
  } else {
    const err = await resp.text();
    console.error('Dispatch failed:', resp.status, err);
    alert(`Failed to dispatch workflow: ${resp.status}`);
    return false;
  }
}
