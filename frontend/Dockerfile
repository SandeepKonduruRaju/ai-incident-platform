# syntax=docker/dockerfile:1
# Build: Node (pinned) runs the typecheck + Vite build. Serve: nginx-unprivileged (pinned, runs as uid 101, port
# 8080), no Node in the final image.
FROM node:24.15.0-alpine3.22 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.31.7-alpine3.24
# The template's ${API_UPSTREAM} and ${NGINX_LOCAL_RESOLVERS} are filled at start by the image's envsubst step (only
# those two). NGINX_ENTRYPOINT_LOCAL_RESOLVERS makes the image export the container's DNS servers (see nginx.conf).
ENV API_UPSTREAM=incident-service:8080 \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1 \
    NGINX_ENVSUBST_FILTER="API_UPSTREAM|NGINX_LOCAL_RESOLVERS"
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
