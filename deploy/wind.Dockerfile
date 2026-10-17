# Wind sidecar (God's Eye View GFS / ECMWF wind server), optional: the map's wind layer.
FROM node:24-alpine
WORKDIR /wind
COPY wind/package.json wind/package-lock.json ./
RUN npm ci --no-audit --no-fund --omit=dev
COPY wind/server.mjs ./
COPY wind/vendor ./vendor
ENV WIND_PORT=8787
EXPOSE 8787
CMD ["node", "server.mjs"]
