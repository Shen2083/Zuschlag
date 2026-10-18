# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f apps/web/Dockerfile .

FROM node:22-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable

FROM base AS build
WORKDIR /repo
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json .npmrc ./
COPY apps/web/package.json apps/web/
COPY packages/sap-schema/package.json packages/sap-schema/
COPY packages/api-types/package.json packages/api-types/
RUN --mount=type=cache,id=pnpm,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter @zuschlag/web...
COPY packages/sap-schema packages/sap-schema
COPY packages/api-types packages/api-types
COPY apps/web apps/web
RUN pnpm --filter @zuschlag/sap-schema build && pnpm --filter @zuschlag/web build

FROM base AS runtime
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
COPY --from=build --chown=app:app /repo/apps/web/.next/standalone ./
COPY --from=build --chown=app:app /repo/apps/web/.next/static ./apps/web/.next/static
USER 10001
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
