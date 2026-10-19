FROM node:24.21.0-bookworm-slim AS dependencies

RUN npm install --global pnpm@12.4.2
WORKDIR /workspace

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter @kribu/web...

FROM dependencies AS builder
COPY apps/web apps/web
RUN pnpm --filter @kribu/web build

FROM node:24.21.0-bookworm-slim AS runtime

ENV NODE_ENV=production
RUN npm install --global pnpm@12.4.2
WORKDIR /workspace

COPY --from=builder --chown=node:node /workspace/package.json ./package.json
COPY --from=builder --chown=node:node /workspace/pnpm-workspace.yaml ./pnpm-workspace.yaml
COPY --from=builder --chown=node:node /workspace/node_modules ./node_modules
COPY --from=builder --chown=node:node /workspace/apps/web ./apps/web

USER node
EXPOSE 3000
CMD ["pnpm", "--filter", "@kribu/web", "start"]

