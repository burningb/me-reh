#!/bin/bash
# 미래 me-Reh v0.4 — 목소리 나선 전시 실행 (인터넷 없이 동작)
# 이 파일을 텍스트 편집기로 열어 아래 설정을 바꿀 수 있습니다.
# ─────────────────────────────────────────────────────────────
IDLE=40        # 이 시간(초) 동안 말이 없으면 세션을 저장하고 다음 관람객을 기다림
LANG_CODE=ko   # 인식 언어: ko 한국어 / en 영어 / ja 일본어
INVERT=0       # 1 = 흰 바탕에 검은 선
DATA=1         # 0 = 수치·측정선 숨김 (글자 선만)
DEMO=0         # 1 = 마이크 없이 예시 대사로 계속 돌림 (화면 점검용)
MODEL="${MEREH_MODEL:-mlx-community/whisper-large-v3-turbo}"
# ─────────────────────────────────────────────────────────────
cd "$(dirname "$0")" || exit 1
PORT=8765
URL="http://localhost:$PORT/?idle=$IDLE&lang=$LANG_CODE&invert=$INVERT&data=$DATA&demo=$DEMO"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -x .venv/bin/python ]; then
  echo "  아직 설치되지 않았습니다. 인터넷이 되는 곳에서 setup_mac.command 를 먼저 실행해 주세요."
  read -n 1 -s -r -p "  아무 키나 누르면 닫힙니다…"; exit 1
fi
if [ ! -x "$CHROME" ]; then
  echo "  Google Chrome을 찾을 수 없습니다. /Applications 에 설치해 주세요."
  read -n 1 -s -r -p "  아무 키나 누르면 닫힙니다…"; exit 1
fi

echo ""
echo "  미래 me-Reh · 목소리 나선 (설치)"
echo "  전시 화면을 끝내려면 Chrome에서 ⌘Q 를 누르세요. 인식 프로그램도 함께 꺼집니다."
echo "  세션 기록은 이 폴더의 archive 에 저장됩니다."
echo ""

export HF_HUB_OFFLINE=1                       # 미리 받아 둔 모델만 사용
caffeinate -dimsu -w $$ &                     # 이 창이 열려 있는 동안 잠자기 방지

.venv/bin/python mereh_whisper_server.py --no-browser --model "$MODEL" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT

# 인식 프로그램이 준비될 때까지 기다림 (처음에는 30초쯤 걸릴 수 있음)
for i in $(seq 1 120); do
  curl -s -o /dev/null "http://localhost:$PORT/" && break
  if ! kill -0 $SERVER 2>/dev/null; then echo "  인식 프로그램이 시작되지 못했습니다. 위 메시지를 확인해 주세요."; read -n 1 -s -r; exit 1; fi
  sleep 1
done

# 전시 전용 Chrome 프로필로 전체 화면(키오스크) 실행
#  - 처음 한 번은 마이크 허용을 눌러 주세요. 이 프로필에 기억됩니다.
"$CHROME" --user-data-dir="$PWD/.chrome-installation" --kiosk --app="$URL" \
  --autoplay-policy=no-user-gesture-required --no-first-run --no-default-browser-check \
  --disable-session-crashed-bubble --noerrdialogs --disable-translate \
  --overscroll-history-navigation=0 >/dev/null 2>&1

echo "  전시 화면이 닫혔습니다."
