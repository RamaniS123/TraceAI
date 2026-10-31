#!/bin/sh
set -eu

# Migrate safely, then replace this process with Uvicorn for normal stop signals.
exec python -m traceai.startup
