FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY builder-lock.json ./
# the package builds in .techradar and runs npm install there; seed it from a lockfile and npm ci
RUN cp -r node_modules/aoe_technology_radar .techradar \
 && cp builder-lock.json .techradar/package-lock.json \
 && (cd .techradar && npm ci) \
 && printf '%s' "$(sha256sum package.json | cut -d' ' -f1)" > .techradar/hash
COPY config.json about.md custom.css ./
COPY public ./public
COPY radar ./radar
RUN npm run build

FROM caddy:alpine
COPY --from=build /app/build /srv
COPY Caddyfile /etc/caddy/Caddyfile
