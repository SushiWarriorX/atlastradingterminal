# NOT CURRENT (2026-11-14): the first stage below builds the desktop web terminal (atlas/web), which was removed on 2026-11-12, so `docker build` fails at its first COPY.
# What the cloud image should serve now is the owner's decision (see atlas/docs/cloud-deploy.md); this file is left as it was until then.
# ATLAS Terminal for cloud hosting: builds the web app, then runs the API (which also serves the web app) as a non-root user.
FROM node:22-slim AS web
WORKDIR /w
COPY atlas/web/package.json atlas/web/package-lock.json ./
RUN npm ci
COPY atlas/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY atlas/backend/ /app/backend/
# editable install: the SQL migrations are read from the source folder
RUN pip install -e /app/backend
COPY --from=web /w/dist /app/web
RUN useradd -m -u 1000 atlas && mkdir /data && chown atlas /data
USER atlas
WORKDIR /data
ENV ATLAS_HOST=0.0.0.0 ATLAS_PORT=8000 ATLAS_DB=/data/atlas.db ATLAS_WEB_DIST=/app/web
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "-m", "atlas_api"]
