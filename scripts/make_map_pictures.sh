#!/usr/bin/env bash
# Make the README pictures from docs/map/index.html: each story, light and dark.
# Needs Google Chrome. Run it from the repository root after the map changes.
set -euo pipefail
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
page="file://$PWD/docs/map/index.html"
shot() { # story, file name, height
  for theme in light dark; do
    "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
      --window-size="1100,$3" --virtual-time-budget=4000 \
      --screenshot="docs/images/map-$2-$theme.png" "$page?shot=$1&theme=$theme" > /dev/null 2>&1
  done
}
shot pr pull-request 715
shot rel release 1195
shot day every-day 770
