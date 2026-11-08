#!/bin/sh
# Before publishing: every commit is authored and committed by the maintainer, and no commit message or tracked
# file contains a private word. The private words are one extended regex in .git/history-banned (never pushed)
# or in $HISTORY_BANNED. Runs as a pre-push hook: ln -s ../../scripts/check_history.sh .git/hooks/pre-push
# With --publish it also searches every past version of every file (what a public repository would expose).
set -eu

publish=0
[ "${1:-}" = "--publish" ] && publish=1

NAME="Tâm Ngô"
EMAIL="ngothtam.me@gmail.com"

cd "$(git rev-parse --show-toplevel)"
banned_file="$(git rev-parse --git-dir)/history-banned"
BANNED="${HISTORY_BANNED:-}"
if [ -z "$BANNED" ] && [ -f "$banned_file" ]; then
    BANNED=$(cat "$banned_file")
fi
fail=0

bad_people=$(git log --format='%H %an <%ae> | %cn <%ce>' | grep -v " $NAME <$EMAIL> | $NAME <$EMAIL>\$" || true)
if [ -n "$bad_people" ]; then
    echo "commits not authored and committed by $NAME <$EMAIL>:"
    echo "$bad_people"
    fail=1
fi

if [ -n "$BANNED" ]; then
    bad_messages=$(git log --format='%H %B' | grep -E "$BANNED" || true)
    if [ -n "$bad_messages" ]; then
        echo "commit messages with private words:"
        echo "$bad_messages"
        fail=1
    fi
    bad_files=$(git grep -nE "$BANNED" || true)
    if [ -n "$bad_files" ]; then
        echo "tracked files with private words:"
        echo "$bad_files"
        fail=1
    fi
    if [ "$publish" = 1 ]; then
        bad_history=$(git log -p --format='commit %H' | grep -nE "^[+-].*($BANNED)" || true)
        if [ -n "$bad_history" ]; then
            echo "past file versions with private words (rewrite history before publishing):"
            echo "$bad_history" | head -20
            fail=1
        fi
    fi
else
    echo "note: no private-word list (.git/history-banned or \$HISTORY_BANNED); checked authorship only"
fi

[ "$fail" = 0 ] || { echo "HISTORY CHECK FAILED"; exit 1; }
