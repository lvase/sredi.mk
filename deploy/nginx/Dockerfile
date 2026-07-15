FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28-alpine
COPY deploy/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=frontend /build/dist /usr/share/nginx/html
