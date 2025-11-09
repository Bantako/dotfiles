# GPGでBitwardenのapi-keyを取得
if [[ -e ~/.secrets/bitwarden_api.env.gpg ]]; then
  source <(gpg --quiet --decrypt ~/.secrets/bitwarden_api.env.gpg)
fi

# Bitwardenセッション取得
bw login --apikey
export BW_SESSION=$(bw unlock --raw "$BW_PASSWORD")

# 必要なAPIキーを取得してexport
items_raw=$(bw list items)
export OPENAI_API_KEY=$(echo "$items_raw" | tr -d '[:cntrl:]' | jq -r '.[] | select(.name=="OPENAI_API_KEY") | .notes')
export DEEPSEEK_API_KEY=$(echo "$items_raw" | tr -d '[:cntrl:]' | jq -r '.[] | select(.name=="DEEPSEEK_API_KEY") | .notes')
export PERPLEXITY_API_KEY=$(echo "$items_raw" | tr -d '[:cntrl:]' | jq -r '.[] | select(.name=="PERPLEXITY_API_KEY") | .notes')
#
# export OPENAI_API_KEY="$(bw get notes OPENAI_API_KEY)"
# export DEEPSEEK_API_KEY="$(bw get notes DEEPSEEK_API_KEY)"
# export PERPLEXITY_API_KEY="$(bw get notes PERPLEXITY_API_KEY)"
