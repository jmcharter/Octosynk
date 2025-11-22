#!/bin/sh
# Run octosynk once immediately on startup
octosynk

# Keep container running for Ofelia to execute scheduled jobs
tail -f /dev/null
