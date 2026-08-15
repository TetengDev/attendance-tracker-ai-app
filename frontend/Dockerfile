# Stage 1: Build the frontend applications
FROM oven/bun:1-alpine AS builder

WORKDIR /app

# Copy lockfile and configuration files
COPY frontend/package.json frontend/bun.lock ./
COPY frontend/tsconfig.base.json ./
COPY frontend/packages/ ./packages/
COPY frontend/apps/ ./apps/

# Install workspace dependencies
RUN bun install --frozen-lockfile

# Compile the Vite static assets for both Admin and Kiosk
RUN bun run build

# Stage 2: Serve the compiled static files using Caddy
FROM caddy:2-alpine

# Copy the custom Caddyfile
COPY infra/Caddyfile /etc/caddy/Caddyfile

# Copy static assets from builder stage
COPY --from=builder /app/apps/admin/dist /srv/admin
COPY --from=builder /app/apps/kiosk/dist /srv/kiosk

EXPOSE 80 443
