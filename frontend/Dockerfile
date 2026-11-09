# Presentation tier: build the React bundle, then serve it from nginx.

FROM node:22-alpine AS build
WORKDIR /src
# Dependencies first, so a source-only change reuses this layer.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine
# The upstream address is substituted at container start by nginx's own
# envsubst entrypoint, so the same image works co-located or across subnets.
ENV API_UPSTREAM=api:9000
COPY nginx/default.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
