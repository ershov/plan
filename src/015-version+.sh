#!/bin/bash

set -ueo pipefail

MAJOR=1
MINOR=0
BUILD=$(git rev-list --count main)
DATE=$(git log -1 --format=%cd --date=short)
VERSION_STR="$MAJOR.$MINOR.$BUILD"
echo "VERSION_A = [$MAJOR, $MINOR, $BUILD]"
echo "VERSION_STR = \"$VERSION_STR\""
echo "VERSION_DATE = \"$DATE\""

GIT_ROOT="$(realpath "$(git rev-parse --show-toplevel)")"
perl -i -pE 's/"version": "(.*?)"/"version": "'"$VERSION_STR"'"/' "$GIT_ROOT"/src/claude-template/plugins/claude-plan/.claude-plugin/plugin.json

