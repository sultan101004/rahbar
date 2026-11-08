# RAHBAR ui: static chat page served by nginx as a non-root user on :8080.
# nginx.conf writes only under /tmp, so the pod mounts an emptyDir there and keeps
# readOnlyRootFilesystem: true.
FROM nginxinc/nginx-unprivileged:1.27.5-alpine3.21
LABEL org.opencontainers.image.title="rahbar-ui"
USER root
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
