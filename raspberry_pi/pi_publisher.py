# /home/capstone/iot/pi_bridge.py
#!/usr/bin/env python3
# ============================
NURSINGHOME_ID       = "NH-001"
ROOM_ID     = "301A"
SERVER_HOST = "121.78.128.175"
MQTT_PORT   = 8883
# ============================

TOPIC = f"pi/{NURSINGHOME_ID}/{ROOM_ID}/data"              # 서버로 올리는 주제
LOCAL_TOPIC_SUB = "esp/+/+/data"                  # esp/{bed_id}/{sensor_id}/data
GATEWAY_STATUS_TOPIC = f"gateway/{ROOM_ID}/status"
ignore_retained = True

LOCAL_BROKER = "localhost"
LOCAL_PORT   = 1883

CA_FILE   = "/home/capstone/Desktop/certs/ca.crt"
CERT_FILE = "/home/capstone/Desktop/certs/client.crt"
KEY_FILE  = "/home/capstone/Desktop/certs/client.key"

# 집계 발행 최소 간격(초)
SERVER_PUB_INTERVAL = float(__import__("os").getenv("SERVER_PUB_INTERVAL", "1.0"))

import os, argparse, json, ssl, signal, sys, threading, time, termios, tty, fcntl
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from paho.mqtt import client as mqtt

# ---------- 모드 설정: server|local|labeling ----------
def _parse_mode():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--mode", choices=["server","local","labeling"], default=None)
    args, _ = p.parse_known_args()
    m = args.mode or os.getenv("PI_MODE", "server").lower()
    return "server" if m not in ("server","local","labeling") else m
MODE = _parse_mode()

# 센서 ID → u1..u4 매핑 기준
ORDER = [f"ESP32-{i}" for i in range(1,5)]  # ESP32-1..ESP32-4 고정
latest = {k: None for k in ORDER}           # 화면 요약용(단일 침대 가정)

def _as_int(v, default=None):
    try:
        if v is None: return default
        return int(round(float(v)))
    except Exception:
        return default

def _norm_sid(s):
    s = str(s).strip()
    if s.lower().startswith("esp32-"):
        return "ESP32-" + s.split("-",1)[1]
    return s

def _print_summary():
    lines = [f"{k}: {latest[k] if latest[k] is not None else '-'}" for k in ORDER]
    sys.stdout.write(f"\033[{len(ORDER)}A")
    for line in lines:
        sys.stdout.write(f"\033[K{line}\n")
    sys.stdout.flush()

def _init_summary_area():
    for _ in ORDER: print("-")
    sys.stdout.flush()

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def now_kst_iso():
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")

# ---------- 라벨 로그(라벨링 모드) ----------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LABEL_LOG = LOG_DIR / "labels.jsonl"
LABEL_NAME = {1: "present", 0: "absent"}

LEFT_KEYS  = set(list("qwertasdfgzxcv"))
RIGHT_KEYS = set(list("yuiop[]hjkl;'bnm,./"))

_stop = False
_stty_saved = None

def _kb_setup():
    global _stty_saved
    fd = sys.stdin.fileno()
    _stty_saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

def _kb_restore():
    if _stty_saved is not None:
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _stty_saved)
        except Exception:
            pass

def _write_label(label_int: int):
    rec = {"ts": now_kst_iso(), "label": int(label_int)}
    for k in ORDER:
        rec[k] = latest.get(k)
    with LABEL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    sys.stdout.write(f"\033[K[label:%d] 기록\n" % label_int)
    _print_summary()

def _keyboard_loop():
    sys.stdout.write("[라벨링] 왼쪽키(q~t, a~g, z~v)=있음 | 오른쪽키(y~], h~', b~/)=없음 | Ctrl+C 종료\n")
    sys.stdout.flush()
    _kb_setup()
    try:
        while not _stop:
            try:
                ch = sys.stdin.read(1)
            except Exception:
                ch = ""
            if not ch:
                time.sleep(0.02); continue
            c = ch.lower()
            if c in LEFT_KEYS:
                _write_label(1)
            elif c in RIGHT_KEYS:
                _write_label(0)
    finally:
        _kb_restore()

# ---------- 서버 퍼블리셔 ----------
server_client = None
if MODE == "server":
    server_client = mqtt.Client(protocol=mqtt.MQTTv311)
    if MQTT_PORT == 8883:
        server_client.tls_set(
            ca_certs=CA_FILE, certfile=CERT_FILE, keyfile=KEY_FILE,
            cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
    server_client.connect(SERVER_HOST, MQTT_PORT, keepalive=60)
    server_client.loop_start()

print(f"[{get_timestamp()}] 모드: {MODE.upper()}")
if MODE == "server":
    print(f"[{get_timestamp()}] 서버 연결 완료: {SERVER_HOST}:{MQTT_PORT}")

# ---------- 로컬 수집 + 집계 ----------
# bed_id별 집계 상태
beds = defaultdict(lambda: {
    "u": {k: None for k in ORDER},  # 센서별 최신값
    "call_button": 0,
    "fall_event": 0,
    "lidar": None,
    "last_pub": 0.0,
    "last_sent_sig": None,          # 중복 전송 방지용 시그니처
})

local_client = None

def on_local_connect(client, userdata, flags, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 성공 (rc={rc})")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)
    print(f"[{get_timestamp()}] 구독 토픽: {LOCAL_TOPIC_SUB}")
    client.publish(GATEWAY_STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[{get_timestamp()}] [상태] 게이트웨이 online 발행: {GATEWAY_STATUS_TOPIC}")

def _build_payload(bed_id: str, bstate: dict):
    # ORDER 순서대로 u1..u4 생성
    uvals = [bstate["u"].get(sid) for sid in ORDER]
    payload = {
        "bed_id": bed_id,
        "call_button": int(bstate["call_button"] or 0),
        "fall_event": int(bstate["fall_event"] or 0),
        "u1": _as_int(uvals[0]),
        "u2": _as_int(uvals[1]),
        "u3": _as_int(uvals[2]),
        "u4": _as_int(uvals[3]),
    }
    if bstate["lidar"] is not None:
        payload["lidar"] = _as_int(bstate["lidar"])
    return payload

def _sig_of(payload: dict):
    # 중복 전송 방지용 요약 시그니처
    keys = ("bed_id","call_button","fall_event","u1","u2","u3","u4","lidar")
    return tuple(payload.get(k) for k in keys)

def _maybe_publish(bed_id: str):
    if MODE != "server":
        return
    bstate = beds[bed_id]
    now = time.time()
    if now - bstate["last_pub"] < SERVER_PUB_INTERVAL:
        return
    payload = _build_payload(bed_id, bstate)
    sig = _sig_of(payload)
    if sig == bstate["last_sent_sig"]:
        return
    res = server_client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
    if res.rc == mqtt.MQTT_ERR_SUCCESS:
        bstate["last_pub"] = now
        bstate["last_sent_sig"] = sig
        print(f"\n[{get_timestamp()}] 서버 전송 OK bed={bed_id} payload={payload}")
    else:
        print(f"\n[{get_timestamp()}] 서버 전송 실패 rc={res.rc}")

def on_local_message(client, userdata, msg):
    global ignore_retained
    if ignore_retained and msg.retain:
        return
    ignore_retained = False

    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"\n[오류] JSON 파싱 실패: {e}")
        return

    parts = msg.topic.split("/")  # esp/{bed_id}/{sensor_id}/data
    if len(parts) < 4:
        print(f"\n[오류] 토픽 형식 오류: {msg.topic}")
        return
    bed_id, sensor_id_from_topic = parts[1], parts[2]
    sensor_id = _norm_sid(data.get("sensor_id") or sensor_id_from_topic)

    ultrasonic = _as_int(data.get("ultrasonic"))
    call_button = _as_int(data.get("call_button"), 0) or 0
    fall_event  = _as_int(data.get("fall_event"), 0) or 0
    lidar       = _as_int(data.get("lidar"))

    # 상태 업데이트
    bstate = beds[bed_id]
    if sensor_id in bstate["u"] and ultrasonic is not None:
        bstate["u"][sensor_id] = ultrasonic
        # 화면 요약(단일 침대 가정)
        if sensor_id in latest:
            latest[sensor_id] = ultrasonic
            _print_summary()

    # 이벤트 비트는 OR로 축적(최근 1회라도 눌리면 1). 필요시 정책 변경.
    if call_button:
        bstate["call_button"] = 1
    if fall_event:
        bstate["fall_event"] = 1
    if lidar is not None:
        bstate["lidar"] = lidar

    # 묶음 발행 시도
    _maybe_publish(bed_id)

    # ACK은 모드와 무관
    ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
    status = "received" if ultrasonic is not None else "skipped"
    client.publish(ack_topic, json.dumps({"status": status}), qos=1, retain=False)

def on_local_disconnect(client, userdata, rc):
    print(f"\n[{get_timestamp()}] 로컬 브로커 연결 해제 (rc={rc})")

def signal_handler(sig, frame):
    global _stop
    _stop = True
    ts = get_timestamp()
    print(f"\n[{ts}] 프로그램 종료 중...")
    if local_client:
        try:
            local_client.publish(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
            print(f"[{ts}] [상태] 게이트웨이 offline 발행: {GATEWAY_STATUS_TOPIC}")
            local_client.disconnect()
        except Exception:
            pass
    if server_client:
        try:
            server_client.loop_stop()
            server_client.disconnect()
        except Exception:
            pass
    _kb_restore()
    print(f"[{ts}] 종료 완료")
    sys.exit(0)

def main():
    global local_client
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    local_client = mqtt.Client()
    local_client.will_set(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
    local_client.on_connect = on_local_connect
    local_client.on_message = on_local_message
    local_client.on_disconnect = on_local_disconnect
    local_client.connect(LOCAL_BROKER, LOCAL_PORT, keepalive=60)

    print(f"[{get_timestamp()}] 게이트웨이 브리지 시작...")
    print(f"  모드: {MODE.upper()}")
    print(f"  요양원 ID: {NURSINGHOME_ID}")
    print(f"  방 ID: {ROOM_ID}")
    if MODE == "server":
        print(f"  서버: {SERVER_HOST}:{MQTT_PORT}")
    print(f"  로컬 브로커: {LOCAL_BROKER}:{LOCAL_PORT}")
    print("="*60 + "\n")

    _init_summary_area()

    if MODE == "labeling":
        t = threading.Thread(target=_keyboard_loop, daemon=True)
        t.start()
        local_client.loop_start()
        try:
            while not _stop:
                time.sleep(0.1)
        finally:
            signal_handler(None, None)
    else:
        local_client.loop_forever()

if __name__ == "__main__":
    main()
