# Cloudflare recommendations (not applied)

GitHub Pages cannot set custom response headers or long cache lifetimes. These changes need a CDN in front of the
site. **Nothing here has been applied. No DNS, Cloudflare or other external settings were changed.** Review and apply
them yourself, and test on a staging hostname first.

## What GitHub Pages gives today (measured with curl, 2026-11-24)
- `cache-control: max-age=600` on every file, including `/assets/*`.
- No `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` or CSP header.

## Suggested Cloudflare setup
1. **Proxy the apex and `www` records** (orange cloud) and keep SSL/TLS mode on *Full (strict)*.
2. **Cache rules**
   - `/assets/*` (fonts, images, screenshots): Edge TTL 1 year, Browser TTL 1 year. File names are not content-hashed,
     so when you replace an asset, give it a new file name or purge the URL.
   - HTML (`/`, `*.html`, `*/`): Browser TTL 10 minutes, Edge TTL 1 hour, with *purge on deploy*.
3. **Response header transform rule** (all paths):
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains` (add `preload` only after you are sure
     every subdomain serves HTTPS)
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: camera=(), microphone=(), geolocation=()`
   - A CSP is optional. The site loads Google Tag Manager/Analytics, so a CSP must allow
     `https://www.googletagmanager.com`, `https://www.google-analytics.com` and
     `https://*.analytics.google.com`. Start with `Content-Security-Policy-Report-Only`.
4. **Compression and protocol**: Brotli on, HTTP/3 on, Early Hints on.
5. **Branded 404**: GitHub Pages already serves `/404.html` from this repo.

## What to check afterwards
- `curl -sI https://fitcheck-fashion.com/assets/fonts/outfit-latin.woff2` shows the long `cache-control`.
- The new headers appear on HTML and asset responses.
- Re-run Lighthouse: repeat-visit performance and the "Serve static assets with an efficient cache policy"
  audit should improve. First-visit scores will not change much.
