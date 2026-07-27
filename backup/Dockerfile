# Off-site backup sidecar for NEXUS.
#
# Based on postgres:16-alpine rather than plain alpine so `pg_dump` is
# guaranteed to match the server major version — a mismatched client refuses
# to dump ("server version X, pg_dump version Y"), and that failure would only
# show up at 02:00 UTC in a container nobody watches. The image is already
# pulled for the `postgres` service, so this costs no extra download.
#
# Added tooling, deliberately minimal:
#   age    — encrypt with a PUBLIC key only. The container cannot decrypt its
#            own backups, so compromising it does not expose history.
#   rclone — single binary, speaks S3, and `rcat` reads stdin so archives can
#            be streamed straight to object storage without a temp file.
#   curl   — Qdrant snapshot API.
#   jq     — manifest construction.
FROM postgres:16-alpine

RUN apk add --no-cache \
      age \
      rclone \
      curl \
      jq \
      tar

COPY backup.sh /usr/local/bin/backup.sh
COPY loop.sh /usr/local/bin/loop.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/loop.sh /usr/local/bin/healthcheck.sh

# Never run as root: the sidecar only ever reads data volumes.
USER postgres

ENTRYPOINT ["/usr/local/bin/loop.sh"]
