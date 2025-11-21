# /home/capstone/iot/code/pi_labeling.py
#!/usr/bin/env python3
# PuTTY / VNC 터미널 모두에서 키 입력 인식, 0.2초 간격 CSV 라벨링 저장

import os, sys, json, time, signal, threading, termios, tty, fcntl
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from collections import defaultdict
from paho.mqtt import client as mqtt

# ===================== 설정 =====================
NURSINGHOME_ID = os.getenv("NURSINGHOME_ID", "NH-001")
ROOM_ID        = os.getenv("ROOM_ID", "301A")
LOCAL_BROKER   = os.getenv("LOCAL_BROKER", "localhost")
LOCAL_PORT     = int(os.getenv("LOCAL_PORT", "1883"))

# ESP 퍼블리시 시작 조건: 게이트웨이 온라인
GATEWAY_STATUS_TOPIC = f"gateway/{ROOM_ID}/status"

# ESP 수집 토픽: esp/{bed_id}/{sensor_id}/data
LOCAL_TOPIC_SUB = "esp/+/+/data"

# 대상 센서 고정 순서(열 순서)
ORDER = [f"ESP32-{i}" for i in range(1,5)]  # ESP32-1..ESP32-4

# 저장 주기(초)
SAMPLE_PERIOD = 0.2

# 출력 경로
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR  = BASE_DIR / "label_out"
OUT_DIR.mkdir(exist_ok=True)
CSV_FILENAME = os.getenv("CSV_NAME", f"labeled_{NURSINGHOME_ID}_{ROOM_ID}.csv")
CSV_PATH = OUT_DIR / CSV_FILENAME

# 키→라벨 매핑
LABEL_KEYS = {
    0: set(list("0qweasdzxc")),
    1: set(list("1rtyfghvbn")),
    2: set(list("2ujmik,ol.p")),
}
# ===================== 설정 끝 =====================

# 상태
lock = threading.Lock()
ignore_retained = True
running = True
current_label = 0  # 시작 기본 라벨
selected_bed_id = None  # 첫 수신 bed_id 자동 선택
beds = defaultdict(lambda: {"u": {k: None for k in ORDER}})  # bed_id → 최신값

def now_kst_ms():
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def _as_int(v):
    try:
        if v is None: return None
        return int(round(float(v)))
    except Exception:
        return None

def _norm_sid(s):
    s = str(s).strip()
    return "ESP32-" + s.split("-",1)[1] if s.lower().startswith("esp32-") else s

def _extract_ultrasonic(d):
    # 페이로드 키 다양성 대응
    for k in ("ultrasonic", "ultrasonic_cm", "u", "distance", "dist_cm"):
        if k in d and d[k] is not None:
            return _as_int(d[k])
    # mm 단위인 경우
    for k in ("ultrasonic_mm", "dist_mm"):
        if k in d and d[k] is not None:
            return _as_int(float(d[k]) / 10.0)
    return None

# ---------- MQTT ----------
client = mqtt.Client()

def on_connect(c, u, f, rc):
    c.subscribe(LOCAL_TOPIC_SUB, qos=1)
    # 게이트웨이 온라인 발행(ESP 전송 트리거)
    c.publish(GATEWAY_STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[{now_kst_ms()}] 로컬 브로커 연결(rc={rc}), 구독: {LOCAL_TOPIC_SUB}")
    print(f"[{now_kst_ms()}] [상태] 게이트웨이 online 발행: {GATEWAY_STATUS_TOPIC}")

def on_message(c, u, msg):
    global ignore_retained, selected_bed_id
    if ignore_retained and msg.retain:
        return
    ignore_retained = False

    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"[파싱오류] {e}")
        return

    parts = msg.topic.split("/")  # esp/{bed_id}/{sensor_id}/data
    if len(parts) < 4:
        return
    bed_id = parts[1]
    sensor_id_from_topic = parts[2]
    sensor_id = _norm_sid(data.get("sensor_id") or sensor_id_from_topic)

    val = _extract_ultrasonic(data)

    with lock:
        if selected_bed_id is None:
            selected_bed_id = bed_id  # 첫 수신 bed_id로 고정
            print(f"[{now_kst_ms()}] 대상 bed_id 자동선택: {selected_bed_id}")
        if bed_id != selected_bed_id:
            return  # 다른 침대 무시
        if sensor_id in ORDER:
            beds[bed_id]["u"][sensor_id] = val
    ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
    status = "received" if val is not None else "skipped"
    c.publish(ack_topic, json.dumps({"status": status}), qos=1, retain=False)

def on_disconnect(c, u, rc):
    print(f"[{now_kst_ms()}] 로컬 브로커 연결 해제(rc={rc})")

client.on_connect = on_connect
client.on_message = on_message
client.on_disconnect = on_disconnect

# ---------- 키보드(비차단, 터미널/SSH/VNC 공통) ----------
_stty_saved = None

def kb_setup():
    global _stty_saved
    try:
        fd = sys.stdin.fileno()
        _stty_saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    except Exception:
        pass  # 터미널이 아닌 경우도 계속 진행

def kb_restore():
    if _stty_saved is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _stty_saved)
        except Exception:
            pass

def keyboard_loop():
    global current_label, running
    print("[키가이드] 0/qweasdzxc=라벨0, 1/rtyfghvbn=라벨1, 2/ujmik,ol.p=라벨2, Ctrl+C 종료")
    kb_setup()
    try:
        while running:
            try:
                ch = sys.stdin.read(1)
            except Exception:
                ch = ""
            if not ch:
                time.sleep(0.02)
                continue
            k = ch.lower()
            for lbl, keys in LABEL_KEYS.items():
                if k in keys:
                    if current_label != lbl:
                        current_label = lbl
                        print(f"[{now_kst_ms()}] 라벨 전환 → {current_label}")
                    break
    finally:
        kb_restore()

# ---------- CSV 저장 ----------
def ensure_trailing_newline(path):
    if not path.exists() or path.stat().st_size == 0:
        return
    with path.open("rb+") as f:
        f.seek(-1, os.SEEK_END)
        if f.read(1) != b"\n":
            f.write(b"\n")
            
def write_header_if_new(path):
    if not path.exists() or path.stat().st_size == 0:
        with path.open("a", encoding="utf-8") as f:
            f.write("timestamp,label,ESP32-1,ESP32-2,ESP32-3,ESP32-4\n")

def writer_loop():
    global running
    write_header_if_new(CSV_PATH)
    next_t = time.perf_counter()
    while running:
        next_t += SAMPLE_PERIOD
        ts = now_kst_ms()
        with lock:
            bed_id = selected_bed_id
            row = ["", "", "", "", ""]
            if bed_id is not None:
                vals = beds[bed_id]["u"]
                row = [vals.get(s) if vals.get(s) is not None else "" for s in ORDER]
            label = current_label
            
            # 유효한 센서 값 개수 확인
            valid_count = sum(1 for v in row if v != "")
        
        # 3개 이상일 때만 저장
        if valid_count >= 3:
            line = f"{ts},{label}," + ",".join(str(v) for v in row) + "\n"
            with CSV_PATH.open("a", encoding="utf-8") as f:
                f.write(line)
        
        # 주기 정밀도 유지
        sleep_d = max(0.0, next_t - time.perf_counter())
        time.sleep(sleep_d)

# ---------- 종료 처리 ----------
def cleanup():
    kb_restore()
    try:
        client.publish(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
        print(f"[{now_kst_ms()}] [상태] 게이트웨이 offline 발행: {GATEWAY_STATUS_TOPIC}")
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass

def sig_handler(sig, frame):
    global running
    running = False
    print(f"\n[{now_kst_ms()}] 종료 요청 수신")
    kb_restore()  # 이 줄 추가!
    cleanup()
    sys.exit(0)

# ---------- 메인 ----------
def main():
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    client.will_set(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
    client.connect(LOCAL_BROKER, LOCAL_PORT, keepalive=60)
    client.loop_start()
    
    ensure_trailing_newline(CSV_PATH)
    write_header_if_new(CSV_PATH)

    t_kb = threading.Thread(target=keyboard_loop, daemon=True)
    t_wr = threading.Thread(target=writer_loop, daemon=True)
    t_kb.start(); t_wr.start()

    print("="*60)
    print(f"[{now_kst_ms()}] 라벨 기록 시작")
    print(f"  저장: {CSV_PATH}")
    print(f"  대상 센서: {', '.join(ORDER)}")
    print(f"  주기: {SAMPLE_PERIOD}s")
    print("="*60)

    try:
        while True:
            time.sleep(1.0)
    finally:
        cleanup()

if __name__ == "__main__":
    main()
