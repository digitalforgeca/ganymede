#!/bin/bash
# Helper script for locally building and restarting the Ganymede gateway during development

echo "Building and reinstalling Ganymede from local brew formula..."
brew reinstall --build-from-source local/ganymede/ganymede

echo "Starting Ganymede..."
ganymede restart
