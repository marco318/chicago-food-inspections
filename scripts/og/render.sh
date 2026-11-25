#!/bin/sh
# Renders scripts/og/og.html to site/og.png with headless Chrome (macOS path).
cd "$(dirname "$0")/../.." && "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
  --hide-scrollbars --force-device-scale-factor=1 --window-size=1200,630 --screenshot=site/og.png "file://$PWD/scripts/og/og.html"
