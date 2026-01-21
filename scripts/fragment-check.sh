#!/bin/bash

wget -qO- https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv sync
source .venv/bin/activate

# Ensure Python can find your package
export PYTHONPATH=$(pwd):$PYTHONPATH

echo "Checking for new changelog fragments against origin/develop..."
git fetch origin develop

NEW_FRAGMENTS=$(git diff --name-status origin/develop...HEAD | \
    grep '^A' | \
    awk '{print $2}' | \
    grep '^newsfragments/.*\.\(feature\|fix\|doc\|removal\|misc\)\.md$' || true)

if [ -z "$NEW_FRAGMENTS" ]; then
    echo "No valid changelog fragments were added."
    echo "Please create one with:"
    echo "  uv run towncrier create <name>.<type>.md -c 'Your message'"
    exit 1
else
    echo "Found new changelog fragment(s):"
    echo "$NEW_FRAGMENTS"
fi