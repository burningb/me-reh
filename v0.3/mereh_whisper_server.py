#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
미래 me-Reh — 로컬 Whisper 인식 서버 (오프라인)

  - 이 폴더의 me-Reh_v0.3_live.html 을 http://localhost:8765/ 로 보여 줍니다.
  - 브라우저가 말 한 덩어리(발화)의 소리를 보내면, Whisper로 글자와
    '단어마다 시작·끝 시간'을 돌려줍니다.
  - 인식 엔진: 맥(Apple 칩) → mlx-whisper,  그 밖 → faster-whisper,
    둘 다 없으면 시험용 엔진(--engine mock).

실행:  python3 mereh_whisper_server.py            (기본 모델: large-v3-turbo)
       python3 mereh_whisper_server.py --model mlx-community/whisper-small-mlx
"""
import argparse
import asyncio
import base64
import json
import os
import re
import sys
import time
import webbrowser
from pathlib import Path

import numpy as np
from aiohttp import web, WSMsgType

HERE = Path(__file__).resolve().parent
HTML = "me-Reh_v0.3_live.html"
SR = 16000

# Whisper가 조용한 구간에서 지어내는 대표적인 문장들 (특히 한국어 방송 자막 학습의 흔적)
HALLUCINATIONS = [
    "시청해주셔서 감사합니다", "시청해 주셔서 감사합니다", "구독과 좋아요", "구독 좋아요",
    "MBC 뉴스", "KBS 뉴스", "SBS 뉴스", "다음 영상에서 만나요", "자막 제공", "배달의민족",
    "Thank you for watching", "Thanks for watching", "Subtitles by", "ご視聴ありがとうございました",
]
_norm = lambda s: re.sub(r"[\s.,!?…·~'\"]", "", s).lower()
HALLU_N = [_norm(h) for h in HALLUCINATIONS]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- 엔진
class MlxEngine:
    name = "mlx-whisper"

    def __init__(self, model):
        import mlx_whisper  # noqa: F401  (없으면 ImportError)
        self.mw = mlx_whisper
        self.model = model

    def run(self, audio, lang, words):
        r = self.mw.transcribe(
            audio, path_or_hf_repo=self.model, language=lang, word_timestamps=words,
            condition_on_previous_text=False, temperature=0.0, no_speech_threshold=0.6,
            compression_ratio_threshold=2.4, logprob_threshold=-1.0, verbose=None)
        return r.get("segments", [])


class FasterEngine:
    name = "faster-whisper"

    def __init__(self, model):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(model, device="auto", compute_type="int8")

    def run(self, audio, lang, words):
        segs, _ = self.m.transcribe(audio, language=lang, word_timestamps=words, beam_size=1,
                                    condition_on_previous_text=False, vad_filter=False)
        out = []
        for s in segs:
            out.append({"text": s.text, "start": s.start, "end": s.end,
                        "no_speech_prob": s.no_speech_prob, "avg_logprob": s.avg_logprob,
                        "words": [{"word": w.word, "start": w.start, "end": w.end,
                                   "probability": w.probability} for w in (s.words or [])]})
        return out


class MockEngine:
    """시험용: 소리 크기로 단어 경계를 찾아, --mock-script 의 문장을 차례로 붙입니다."""
    name = "mock"

    def __init__(self, script):
        self.lines = json.loads(Path(script).read_text(encoding="utf-8")) if script else []
        self.i = 0

    def _runs(self, audio):
        hop = 160  # 10ms
        n = len(audio) // hop
        if n == 0:
            return []
        e = np.sqrt(np.mean(audio[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
        db = 20 * np.log10(e)
        on = db > (np.percentile(db, 95) - 30)
        runs, start = [], None
        for k, v in enumerate(on):
            if v and start is None:
                start = k
            if not v and start is not None:
                runs.append([start, k]); start = None
        if start is not None:
            runs.append([start, n])
        merged = []  # 30ms보다 짧은 틈은 같은 단어로 봄
        for r in runs:
            if merged and r[0] - merged[-1][1] < 3:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return [(a * hop / SR, b * hop / SR) for a, b in merged if b - a >= 5]

    def run(self, audio, lang, words):
        if float(np.max(np.abs(audio))) < 1e-4:  # 무음(예열 등)
            return []
        runs = self._runs(audio)
        if not runs or not self.lines:
            return []
        idx = min(self.i, len(self.lines) - 1)
        text = self.lines[idx]
        ws = text.split()
        if words:  # 확정 결과일 때만 다음 문장으로 넘어감
            self.i += 1
        if len(runs) >= len(ws):
            spans = runs[: len(ws)]
        else:  # 경계를 못 찾으면 전체를 고르게 나눔
            a, b = runs[0][0], runs[-1][1]
            spans = [(a + (b - a) * k / len(ws), a + (b - a) * (k + 1) / len(ws)) for k in range(len(ws))]
        if not words:  # 중간 결과: 지금까지 들린 만큼만
            ws = ws[: max(1, min(len(ws), len(runs)))]
        return [{"text": " " + " ".join(ws), "no_speech_prob": 0.0, "avg_logprob": -0.2,
                 "words": [{"word": " " + w, "start": s[0], "end": s[1], "probability": 0.9}
                           for w, s in zip(ws, spans)]}]


def make_engine(args):
    tried = []
    order = [args.engine] if args.engine != "auto" else ["mlx", "faster"]
    for name in order:
        try:
            if name == "mlx":
                return MlxEngine(args.model)
            if name == "faster":
                return FasterEngine(args.fw_model)
            if name == "mock":
                return MockEngine(args.mock_script)
        except ImportError as e:
            tried.append(f"{name}: {e}")
    log("인식 엔진을 불러오지 못했습니다:", "; ".join(tried))
    log("맥이라면 setup_mac.command 를 먼저 실행해 주세요.")
    sys.exit(1)


# ---------------------------------------------------------------- 결과 정리
def clean(segments, offset_ok=True):
    """환각·무음 구간을 버리고 [{w,start,end}] 와 문장으로 정리"""
    words, texts = [], []
    for s in segments:
        txt = (s.get("text") or "").strip()
        if not txt:
            continue
        if s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0:
            continue
        n = _norm(txt)
        if any(h and h in n for h in HALLU_N):
            continue
        texts.append(txt)
        for w in s.get("words") or []:
            t = (w.get("word") or "").strip()
            if t:
                words.append({"w": t, "start": float(w["start"]), "end": float(w["end"]),
                              "p": float(w.get("probability", 1))})
    return " ".join(texts).strip(), words


# ---------------------------------------------------------------- 연결별 작업
class Session:
    """확정 요청은 순서대로 모두 처리하고, 중간 요청은 가장 최신 것만 처리"""

    def __init__(self, ws, engine, lock):
        self.ws, self.engine, self.lock = ws, engine, lock
        self.finals = []
        self.partial = None
        self.wake = asyncio.Event()
        self.alive = True

    def add(self, req):
        if req.get("partial"):
            self.partial = req
        else:
            if self.partial and self.partial.get("id") == req.get("id"):
                self.partial = None
            self.finals.append(req)
        self.wake.set()

    async def worker(self):
        loop = asyncio.get_running_loop()
        while self.alive:
            await self.wake.wait()
            self.wake.clear()
            while self.alive and (self.finals or self.partial):
                req = self.finals.pop(0) if self.finals else self.partial
                if req is self.partial:
                    self.partial = None
                audio = np.frombuffer(base64.b64decode(req["pcm"]), dtype="<i2").astype(np.float32) / 32768.0
                if len(audio) < SR * 0.25:
                    if not req.get("partial"):
                        await self.send({"type": "final", "id": req["id"], "text": "", "words": []})
                    continue
                final = not req.get("partial")
                t = time.time()
                async with self.lock:  # 모델은 한 번에 하나만
                    try:
                        segs = await loop.run_in_executor(None, self.engine.run, audio, req.get("lang", "ko"), final)
                    except Exception as e:  # noqa: BLE001
                        log("인식 오류:", e)
                        segs = []
                text, words = clean(segs)
                dt = time.time() - t
                if final:
                    log(f"[확정] {len(audio)/SR:.1f}s 소리 → {dt:.2f}s  {text}")
                await self.send({"type": "final" if final else "partial", "id": req["id"],
                                 "text": text, "words": words, "took": round(dt, 3)})

    async def send(self, obj):
        if not self.ws.closed:
            await self.ws.send_str(json.dumps(obj, ensure_ascii=False))


async def ws_handler(request):
    ws = web.WebSocketResponse(max_msg_size=64 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    app = request.app
    s = Session(ws, app["engine"], app["lock"])
    task = asyncio.create_task(s.worker())
    await s.send({"type": "hello", "engine": app["engine"].name, "model": app["model_name"]})
    log("화면이 연결되었습니다.")
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    req = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if req.get("type") == "utt":
                    s.add(req)
    finally:
        s.alive = False
        s.wake.set()
        task.cancel()
        log("화면 연결이 끊어졌습니다.")
    return ws


async def index(request):
    return web.FileResponse(HERE / HTML)


def main():
    ap = argparse.ArgumentParser(description="me-Reh 로컬 Whisper 인식 서버")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--engine", default="auto", choices=["auto", "mlx", "faster", "mock"])
    ap.add_argument("--model", default="mlx-community/whisper-large-v3-turbo", help="mlx-whisper 모델")
    ap.add_argument("--fw-model", default="small", help="faster-whisper 모델 (맥이 아닐 때)")
    ap.add_argument("--mock-script", default="", help="시험용 엔진이 돌려줄 문장 목록(JSON)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    log("인식 엔진을 준비하는 중… (처음에는 몇십 초 걸릴 수 있습니다)")
    engine = make_engine(args)
    t = time.time()
    try:  # 미리 한 번 돌려서 첫 문장이 늦지 않게
        engine.run(np.zeros(SR, dtype=np.float32), "ko", True)
    except Exception as e:  # noqa: BLE001
        log("모델을 불러오지 못했습니다:", e)
        log("인터넷이 되는 곳에서 setup_mac.command 를 한 번 실행해 모델을 내려받아 주세요.")
        sys.exit(1)
    model_name = args.model if engine.name == "mlx-whisper" else (args.fw_model if engine.name == "faster-whisper" else "mock")
    log(f"준비 완료: {engine.name} · {model_name} ({time.time()-t:.1f}s)")

    app = web.Application()
    app["engine"], app["lock"], app["model_name"] = engine, asyncio.Lock(), model_name
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/files/", HERE, show_index=False)
    url = f"http://localhost:{args.port}/"
    log(f"Chrome에서 {url} 을 여세요. 끝내려면 이 창에서 Ctrl+C.")
    if not args.no_browser:
        async def _open(_app):
            asyncio.get_running_loop().call_later(1.0, lambda: webbrowser.open(url))
        app.on_startup.append(_open)
    web.run_app(app, host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":
    main()
