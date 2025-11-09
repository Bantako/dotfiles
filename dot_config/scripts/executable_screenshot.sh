#!/bin/bash

function take_screenshot() {
  local scr_dir="$XDG_PICTURES_DIR/Screenshots"
  local scr_path="$scr_dir/screenshot_$(date +"%Y%m%d_%H%M%S").png"

  if [ "$1" = "-a" ]; then
    # 画面全体のスクショを撮る
    grim $scr_path
  else
    # 範囲を指定してスクショを撮る
    grim -g "$(slurp)" $scr_path
  fi
}

take_screenshot "$@"
