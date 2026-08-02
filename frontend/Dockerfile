FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_OMNI_UNIFIED_SHELL=true
ENV NEXT_PUBLIC_OMNI_UNIFIED_SHELL=${NEXT_PUBLIC_OMNI_UNIFIED_SHELL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV VIDEO_ANALYSIS_SERVICE_URL=http://video-analysis:8006
ENV LIVESTREAM_ANALYSIS_SERVICE_URL=http://livestream-analysis:8007
ENV NEWS_AGGREGATOR_URL=http://news-aggregator:8005
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ARG OMNI_BUILD_COMMIT=unknown
ARG OMNI_BUILD_SOURCE_FINGERPRINT=unknown
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV OMNI_BUILD_COMMIT=${OMNI_BUILD_COMMIT}
ENV OMNI_BUILD_SOURCE_FINGERPRINT=${OMNI_BUILD_SOURCE_FINGERPRINT}
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "run", "start"]
