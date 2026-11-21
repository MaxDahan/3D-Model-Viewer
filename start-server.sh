#!/bin/bash

# Start a local HTTP server for the 3D viewer
PORT=${1:-8080}

echo "Starting 3D Model Viewer on http://localhost:$PORT"
echo "Press Ctrl+C to stop"

# Use Python's built-in HTTP server
python3 -m http.server $PORT --directory /home/maxime/BRIAN-PORTFOLIO
