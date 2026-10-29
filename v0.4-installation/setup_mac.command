#!/bin/bash
# 미래 me-Reh v0.4 목소리 나선 (설치 버전) — 로컬 Whisper 설치 (맥, Apple 칩)
# 인터넷이 되는 곳에서 한 번만 실행하면 됩니다. 약 2GB를 내려받습니다.
cd "$(dirname "$0")" || exit 1
MODEL="${MEREH_MODEL:-mlx-community/whisper-large-v3-turbo}"

echo ""
echo "  미래 me-Reh · 로컬 Whisper 설치"
echo "  ─────────────────────────────────────"

if [ "$(uname -m)" != "arm64" ]; then
  echo "  이 설치 스크립트는 Apple 칩(M1~M4) 맥 전용입니다."
  read -n 1 -s -r -p "  아무 키나 누르면 닫힙니다…"; exit 1
fi

# 1) uv: 파이썬과 패키지를 이 폴더 안에만 설치해 주는 도구 (맥 시스템은 건드리지 않음)
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
if [ ! -x "$UV" ]; then
  echo "  [1/4] 설치 도구(uv)를 내려받는 중…"
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "  uv 설치 실패. 인터넷 연결을 확인해 주세요."; read -n 1 -s -r; exit 1; }
  UV="$HOME/.local/bin/uv"
else
  echo "  [1/4] 설치 도구(uv) 확인됨"
fi

# 2) 파이썬 3.12 가상환경 (.venv 폴더)
echo "  [2/4] 파이썬 환경을 만드는 중…"
"$UV" venv .venv --python 3.12 --quiet || { echo "  파이썬 환경을 만들지 못했습니다."; read -n 1 -s -r; exit 1; }

# 3) 패키지
echo "  [3/4] Whisper(mlx-whisper)와 서버 패키지를 설치하는 중…"
"$UV" pip install --python .venv/bin/python --quiet mlx-whisper aiohttp numpy || { echo "  패키지 설치 실패."; read -n 1 -s -r; exit 1; }

# 4) 모델 내려받기 (공연장에서 인터넷 없이 쓰려면 여기서 미리 받아 둬야 함)
echo "  [4/4] 음성 인식 모델을 내려받는 중… ($MODEL, 약 1.6GB)"
.venv/bin/python - <<PY || { echo "  모델을 내려받지 못했습니다. 인터넷 연결을 확인하고 다시 실행해 주세요."; read -n 1 -s -r; exit 1; }
from huggingface_hub import snapshot_download
snapshot_download("$MODEL")
import numpy as np, mlx_whisper
mlx_whisper.transcribe(np.zeros(16000, dtype=np.float32), path_or_hf_repo="$MODEL", language="ko")
print("  모델 시험 실행 성공")
PY

echo ""
if [ ! -d "/Applications/Google Chrome.app" ]; then
  echo "  ※ Google Chrome이 없습니다. 전시 화면은 Chrome 전체 화면(키오스크)으로 띄웁니다."
  echo "    https://www.google.com/chrome 에서 설치해 주세요."
fi
echo "  설치가 끝났습니다. 이제 인터넷 없이도 start_installation.command 로 실행할 수 있습니다."
echo ""
read -n 1 -s -r -p "  아무 키나 누르면 닫힙니다…"
