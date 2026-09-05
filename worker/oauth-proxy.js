/**
 * Cloudflare Worker — GitHub OAuth token exchange proxy.
 *
 * This worker receives the OAuth authorization code from GitHub's redirect,
 * exchanges it for an access token using the OAuth App's client secret
 * (which stays server-side, never exposed to the browser), and redirects
 * back to the GitHub Pages site with the token in the URL fragment hash
 * (which is never sent to servers in HTTP requests).
 *
 * Secrets (set via `wrangler secret put`):
 *   GITHUB_CLIENT_ID     — OAuth App client ID
 *   GITHUB_CLIENT_SECRET — OAuth App client secret
 *   PAGES_URL            — GitHub Pages base URL (e.g. https://enterprise-av.github.io/room-sync)
 *
 * Deploy:
 *   npx wrangler deploy worker/oauth-proxy.js --name room-sync-auth
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': env.PAGES_URL || '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // OAuth callback
    if (url.pathname === '/callback') {
      const code = url.searchParams.get('code');
      if (!code) {
        return new Response('Missing authorization code', { status: 400 });
      }

      // Exchange authorization code for access token
      const tokenResp = await fetch('https://github.com/login/oauth/access_token', {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          client_id: env.GITHUB_CLIENT_ID,
          client_secret: env.GITHUB_CLIENT_SECRET,
          code: code,
        }),
      });

      const data = await tokenResp.json();

      if (data.error) {
        return new Response(`OAuth error: ${data.error_description || data.error}`, {
          status: 400,
        });
      }

      const token = data.access_token;
      if (!token) {
        return new Response('No access token received', { status: 500 });
      }

      // Redirect back to Pages with token in fragment hash.
      // The fragment is never sent to the server in HTTP requests,
      // so the token stays client-side only.
      const pagesUrl = env.PAGES_URL || 'https://enterprise-av.github.io/room-sync';
      return Response.redirect(`${pagesUrl}/#token=${token}`, 302);
    }

    return new Response('Room Sync OAuth Proxy', { status: 200 });
  },
};
