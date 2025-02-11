#!/bin/sh

# デスクトップディレクトリを英語にする
LANG=C xdg-user-dirs-update --force
cd
rm -r "デスクトップ" "ダウンロード" "テンプレート" "公開" "ドキュメント" "音楽" "画像" "ビデオ"
