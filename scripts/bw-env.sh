# shellcheck shell=sh
# 依存: bw, jq

function bw_unlock() {
  export BW_SESSION="$(bw unlock --raw)";
}

# bw_set VAR ITEM SPEC   # SPEC = password | notes | field:NAME
bw_set() {
  local var="$1" item="$2" spec="$3"
  bw_unlock || return 1
  local val=""
  case "$spec" in
    password) val="$(bw get password "$item" 2>/dev/null)" ;;
    notes)    val="$(bw get notes "$item" 2>/dev/null)" ;;
    field:*)  val="$(bw get item "$item" 2>/dev/null | jq -r --arg k "${spec#field:}" '.fields[]? | select(.name==$k) | .value')" ;;
    *)        return 2 ;;
  esac
  [ -n "$val" ] || return 3
  export "$var=$val"
  return 0
}
bw_set_all() {
  bw_set OPENAI_API_KEY OPENAI_API_KEY notes || return 1
  bw_set DEEPSEEK_API_KEY DEEPSEEK_API_KEY notes || return 1
  bw_set PERPLEXITY_API_KEY dev/perplexity notes || return 1
  return 0
}
