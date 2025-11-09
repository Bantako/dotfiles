#!/bin/bash

# 秘密保持ディレクトリ
secret_dir="$HOME/.secrets"
secret_file_plain="$secret_dir/bitwarden_api.env"
secret_file_enc="$secret_dir/bitwarden_api.env.gpg"

mkdir -p "$secret_dir"
chmod 700 "$secret_dir"

# 対話型で入力
read -s -p "Bitwarden Master Password: " BW_PASSWORD; echo
read -p "Bitwarden Client ID: " BW_CLIENTID
read -p "Bitwarden Client Secret: " BW_CLIENTSECRET

# 一時平文ファイルを作成
cat > "$secret_file_plain" <<EOF
export BW_PASSWORD="${BW_PASSWORD}"
export BW_CLIENTID="${BW_CLIENTID}"
export BW_CLIENTSECRET="${BW_CLIENTSECRET}"
EOF

# gpgで暗号化
gpg -r "$(gpg --list-keys --with-colons | awk -F: '/^uid:/ {print $10; exit}')" -e "$secret_file_plain"

# 移動
# mv "${secret_file_plain}.gpg" "$secret_file_enc"

# 平文削除&パーミッション設定
shred -u "$secret_file_plain"
chmod 600 "$secret_file_enc"

echo "bitwarden_api.env.gpgが生成されました: $secret_file_enc"
