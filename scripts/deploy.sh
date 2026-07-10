#!/usr/bin/env bash
set -e

echo "Starting Ganymede Deploy Pipeline..."
echo "-------------------------------------"

echo "1. Running unit/e2e tests..."
.venv/bin/python -m unittest discover -s tests

echo "2. Building the latest code..."
# Ensure build module is available
.venv/bin/python -m pip install --quiet build
.venv/bin/python -m build

echo "3. Bumping tag..."
# Call our bump_tag script
bash scripts/bump_tag.sh patch

echo "4. Pushing code and tags..."
# Get the current branch
BRANCH=$(git rev-parse --abbrev-ref HEAD)

echo "Pushing branch: $BRANCH"
git push origin "$BRANCH"
git push origin --tags

echo "-------------------------------------"
echo "Deploy Pipeline Completed Successfully!"
