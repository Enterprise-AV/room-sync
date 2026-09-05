/* GitHub OAuth authentication for Room Sync.
 *
 * Flow:
 * 1. User clicks "Sign in with GitHub"
 * 2. Redirect to GitHub OAuth with the OAuth App's client ID
 * 3. GitHub redirects to Cloudflare Worker with authorization code
 * 4. Worker exchanges code for token (client secret stays server-side)
 * 5. Worker redirects back here with token in the URL fragment hash
 * 6. Token stored in sessionStorage (cleared on tab close)
 * 7. Org membership verified before allowing write actions
 */

// Configuration — update these after creating the OAuth App and Worker
const OAUTH_CLIENT_ID = '';       // GitHub OAuth App client ID
const OAUTH_WORKER_URL = '';      // Cloudflare Worker callback URL
const GITHUB_ORG = 'Enterprise-AV';
const REPO_OWNER = 'Enterprise-AV';
const REPO_NAME = 'room-sync';

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
  return !!getToken();
}

function getUser() {
  return sessionStorage.getItem('github_user');
}

// Check for token in URL hash on page load (returned from OAuth callback)
(function checkHashToken() {
  const hash = window.location.hash;
  if (hash.startsWith('#token=')) {
    const token = hash.substring(7);
    setToken(token);
    // Clean the URL
    history.replaceState(null, '', window.location.pathname + window.location.search);
    // Verify org membership
    verifyMembership(token);
  } else if (isAuthenticated()) {
    updateAuthUI();
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
      alert('Authentication failed. Please try again.');
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
      alert(`You must be a member of the ${GITHUB_ORG} organization to use this tool.`);
      return;
    }

    updateAuthUI();
  } catch (e) {
    console.error('Auth verification failed:', e);
    clearToken();
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
  const scope = encodeURIComponent('repo');
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
