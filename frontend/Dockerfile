# Stage 1: Build
FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# We need to ensure output is set to standalone in next.config.ts for this to work
RUN npm run build

# Stage 2: Runtime (Node.js for Next.js standalone)
# Using Node runtime instead of Nginx because .next/standalone is a Node server, not static files.
FROM node:20-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app

# Run as non-root user
RUN groupadd -r neuroflow && useradd -r -g neuroflow neuroflow

COPY --from=builder /app/public ./public
# The standalone build includes everything needed to run the server
COPY --from=builder --chown=neuroflow:neuroflow /app/.next/standalone ./
COPY --from=builder --chown=neuroflow:neuroflow /app/.next/static ./.next/static

USER neuroflow
EXPOSE 3000

# Next.js standalone outputs a server.js file
CMD ["node", "server.js"]
