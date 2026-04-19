{ config, pkgs, lib, ... }:

let
  modelDir = "${config.home.homeDirectory}/.local/share/bonsai/models";

  # PrismML fork of llama.cpp - Q1_0（ternary, type 41）サポート付き
  # nixpkgs版は type 41 未対応のため独自ビルドが必要
  prismml-llama-cpp = pkgs.llama-cpp.overrideAttrs (_old: {
    # LLAMA_BUILD_NUMBER は整数を要求するため数値のみ
    version = "0";
    src = pkgs.fetchFromGitHub {
      owner = "PrismML-Eng";
      repo = "llama.cpp";
      rev = "e2d67422cc70535166101051f1ddf988045d8570";
      hash = "sha256-OxdxTUq6njqwkFPYY0/qg3rthmMVtjaVxhFnQQRsCsM=";
      fetchSubmodules = true;
      leaveDotGit = true;
      postFetch = ''
        git -C "$out" rev-parse --short HEAD > $out/COMMIT
        find "$out" -name .git -print0 | xargs -0 rm -rf
      '';
    };
    patches = [];
    # PrismMLフォークのwebui用npm依存のhash
    npmDepsHash = "sha256-RAFtsbBGBjteCt5yXhrmHL39rIDJMCFBETgzId2eRRk=";
  });

  # モデルダウンロードスクリプト
  # 使い方: bonsai-fetch [1.7b|4b|8b]
  bonsai-fetch = pkgs.writeShellScriptBin "bonsai-fetch" ''
    set -euo pipefail
    mkdir -p "${modelDir}"

    MODEL=''${1:-4b}
    case "$MODEL" in
      1.7b|1.7B)
        FILE="Bonsai-1.7B-Q1_0.gguf"
        REPO="prism-ml/Bonsai-1.7B-gguf"
        ;;
      4b|4B)
        FILE="Bonsai-4B-Q1_0.gguf"
        REPO="prism-ml/Bonsai-4B-gguf"
        ;;
      8b|8B)
        FILE="Bonsai-8B-Q1_0.gguf"
        REPO="prism-ml/Bonsai-8B-gguf"
        ;;
      *)
        echo "使い方: bonsai-fetch [1.7b|4b|8b]" >&2
        exit 1
        ;;
    esac

    DEST="${modelDir}/$FILE"
    if [[ -f "$DEST" ]]; then
      echo "既にダウンロード済みです: $DEST"
      exit 0
    fi

    echo "ダウンロード中: $FILE ..."
    ${pkgs.curl}/bin/curl -L --progress-bar \
      -o "$DEST.tmp" \
      "https://huggingface.co/$REPO/resolve/main/$FILE"
    mv "$DEST.tmp" "$DEST"
    echo "完了: $DEST"
  '';

  # 対話チャットスクリプト
  # 環境変数 BONSAI_MODEL でモデルパスを上書き可能
  bonsai-chat = pkgs.writeShellScriptBin "bonsai-chat" ''
    set -euo pipefail
    MODEL_FILE=''${BONSAI_MODEL:-"${modelDir}/Bonsai-4B-Q1_0.gguf"}

    if [[ ! -f "$MODEL_FILE" ]]; then
      echo "モデルが見つかりません: $MODEL_FILE" >&2
      echo "先に 'bonsai-fetch 4b' を実行してください" >&2
      exit 1
    fi

    exec ${prismml-llama-cpp}/bin/llama-cli \
      -m "$MODEL_FILE" \
      --temp 0.7 \
      -c 4096 \
      -cnv \
      "$@"
  '';

  # OpenAI互換APIサーバー（ポートデフォルト: 11435）
  bonsai-server = pkgs.writeShellScriptBin "bonsai-server" ''
    set -euo pipefail
    MODEL_FILE=''${BONSAI_MODEL:-"${modelDir}/Bonsai-4B-Q1_0.gguf"}
    PORT=''${BONSAI_PORT:-11435}

    if [[ ! -f "$MODEL_FILE" ]]; then
      echo "モデルが見つかりません: $MODEL_FILE" >&2
      echo "先に 'bonsai-fetch 4b' を実行してください" >&2
      exit 1
    fi

    echo "Bonsai API サーバー起動: http://127.0.0.1:$PORT"
    exec ${prismml-llama-cpp}/bin/llama-server \
      -m "$MODEL_FILE" \
      --host 127.0.0.1 \
      --port "$PORT" \
      -c 4096 \
      -np 1
  '';
in {
  home.packages = [
    prismml-llama-cpp
    bonsai-fetch
    bonsai-chat
    bonsai-server
  ];
}
