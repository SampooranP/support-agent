# The Next.js app (chat and approvals), as a standalone Node server. The public demo runs on Vercel;
# this image is for running the whole stack locally with compose.yaml, or on any container host.
#   docker build -t support-agent-web web
#   docker run -e AGENT_API_URL=http://host.docker.internal:8000 -p 3000:3000 support-agent-web
# AGENT_API_URL, AGENT_API_SECRET and DEMO_PASSWORD are read at runtime.

FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-slim
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
