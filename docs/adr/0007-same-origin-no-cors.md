# ADR 0007: Same origin for UI and API (no CORS)

Status: accepted (milestone 4)

## Context

The React UI calls incident-service's API. Served from different origins, every API call would need CORS, with
preflight requests, an allow-list to maintain, and a configuration mistake that can expose the API to other sites.

## Decision

The browser only ever talks to one origin:

- **compose**: the UI's nginx (non-root) serves the build and proxies `/api/` to incident-service;
- **development**: the Vite dev server proxies `/api` the same way;
- **Kubernetes**: the Ingress routes `/` to the UI and `/api` to incident-service on the same host.

CORS stays off by default (`app.cors.allowed-origins` empty: every cross-origin request is refused); it can be enabled
for one development origin. The UI's Content-Security-Policy has `connect-src 'self'`.

nginx resolves the API's name at request time (`resolver` from the container's `/etc/resolv.conf`, `valid=10s`, a
variable in `proxy_pass`), so a recreated incident-service container with a new IP does not cause 502s until the UI
is restarted.

## Consequences

- No preflights, no allow-list, and the CSP can stay strict.
- The proxy is one more hop and one more component that must forward headers (`X-Forwarded-*`, `Host`).
- nginx's resolver ignores DNS search domains, so `API_UPSTREAM` must be a name that resolves as written (a compose
  service name, or the full `*.svc.cluster.local` name in Kubernetes).

## Alternatives considered

- **Separate origins with CORS**: works, but adds configuration and failure modes for no benefit here.
- **Serve the UI from Spring Boot**: couples UI and API deployments and builds.
