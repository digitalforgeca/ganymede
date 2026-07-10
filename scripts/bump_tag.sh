#!/usr/bin/env bash
set -e

# Get the latest tag, or default to v0.0.0
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")

echo "Latest tag: $LATEST_TAG"

# Extract major, minor, patch
if [[ $LATEST_TAG =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    MAJOR="${BASH_REMATCH[1]}"
    MINOR="${BASH_REMATCH[2]}"
    PATCH="${BASH_REMATCH[3]}"
else
    echo "Error: Latest tag ($LATEST_TAG) doesn't match vX.Y.Z format. Exiting."
    exit 1
fi

BUMP_TYPE=${1:-patch}

if [ "$BUMP_TYPE" = "major" ]; then
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
elif [ "$BUMP_TYPE" = "minor" ]; then
    MINOR=$((MINOR + 1))
    PATCH=0
elif [ "$BUMP_TYPE" = "patch" ]; then
    PATCH=$((PATCH + 1))
else
    echo "Invalid bump type: $BUMP_TYPE. Use 'major', 'minor', or 'patch'."
    exit 1
fi

NEW_TAG="v${MAJOR}.${MINOR}.${PATCH}"
NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"

echo "Bumping version to $NEW_TAG"

# Update pyproject.toml version
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^version = .*/version = \"$NEW_VERSION\"/" pyproject.toml
else
    sed -i "s/^version = .*/version = \"$NEW_VERSION\"/" pyproject.toml
fi

git add pyproject.toml
git commit -m "Bump version to $NEW_TAG" || echo "Nothing to commit for pyproject.toml"

git tag -a "$NEW_TAG" -m "Release $NEW_TAG"
echo "Successfully created tag $NEW_TAG"
