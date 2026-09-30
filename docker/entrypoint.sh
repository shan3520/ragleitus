#!/bin/sh
# Bring the schema up to date, then start the server.
set -e
alembic upgrade head
exec "$@"
