FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY config.json about.md custom.css ./
COPY public ./public
COPY radar ./radar
RUN npm run build

FROM caddy:alpine
COPY --from=build /app/build /srv
COPY Caddyfile /etc/caddy/Caddyfile
