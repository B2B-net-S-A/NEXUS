# Budzik okna wdrożeń NEXUSA — o 18:05, 20:05 i 22:05 (Warszawa) uruchamia
# workflow Deploy przez API GitHuba. Powód i działanie: loop.sh.
#
#   curl   — wywołanie API GitHuba.
#   tzdata — sloty liczone w czasie warszawskim, także po zmianie czasu.
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

RUN apk add --no-cache curl tzdata \
    && adduser -D -H -u 10001 budzik

COPY loop.sh /usr/local/bin/loop.sh

USER budzik

ENTRYPOINT ["/bin/sh", "/usr/local/bin/loop.sh"]
