#!/bin/bash
# 미래 me-Reh — 실행 (인터넷 없이 동작)
cd "$(dirname "$0")" || exit 1
MODEL="${MEREH_MODEL:-mlx-community/whisper-large-v3-turbo}"

if [ ! -x .venv/bin/python ]; then
  echo "  아직 설치되지 않았습니다. 인터넷이 되는 곳에서 setup_mac.command 를 먼저 실행해 주세요."
  read -n 1 -s -r -p "  아무 키나 누르면 닫힙니다…"; exit 1
fi

# 미리 받아 둔 모델만 쓰고 인터넷에 접속하지 않음
export HF_HUB_OFFLINE=1

# 서버가 준비될 즈음 Chrome으로 화면을 엶 (Chrome이 없으면 기본 브라우저)
( for i in $(seq 1 60); do
    sleep 1
    if curl -s -o /dev/null http://localhost:8765/; then
      open -a "Google Chrome" "http://localhost:8765/" 2>/dev/null || open "http://localhost:8765/"
      break
    fi
  done ) &

echo ""
echo "  미래 me-Reh · 로컬 Whisper"
echo "  이 창을 닫으면 인식이 멈춥니다. 공연이 끝날 때까지 열어 두세요."
echo ""
.venv/bin/python mereh_whisper_server.py --no-browser --model "$MODEL"
read -n 1 -s -r -p "  종료되었습니다. 아무 키나 누르면 닫힙니다…"
