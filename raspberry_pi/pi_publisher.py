# /home/capstone/iot/pi_bridge.py
#!/usr/bin/env python3
# ============================
NH_ID       = "NH-001"
ROOM_ID     = "301A"
SERVER_HOST = "121.78.128.175"
MQTT_PORT   = 8883
# ============================

TOPIC = f"pi/{NH_ID}/{ROOM_ID}/data"
LOCAL_TOPIC_SUB = "esp/+/+/data"                # esp/{bed_id}/{sensor_id}/data
GATEWAY_STATUS_TOPIC = f"gateway/{ROOM_ID}/status"
ignore_retained = True

LOCAL_BROKER = "localhost"
LOCAL_PORT   = 1883

CA_FILE   = "/home/capstone/Desktop/certs/ca.crt"
CERT_FILE = "/home/capstone/Desktop/certs/client.crt"
KEY_FILE  = "/home/capstone/Desktop/certs/client.key"

import os, argparse, json, ssl, signal, sys, threading, time, termios, tty, fcntl
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from paho.mqtt import client as mqtt

# ---------- 모드 설정: server|local|labeling ----------
def _parse_mode():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--mode", choices=["server","local","labeling"], default=None)
    args, _ = p.parse_known_args()
    m = args.mode or os.getenv("PI_MODE", "server").lower()
    return "server" if m not in ("server","local","labeling") else m
MODE = _parse_mode()

ORDER = [f"ESP32-{i}" for i in range(1,5)]
latest = {k: None for k in ORDER}

def _as_int(v, default=None):
    try: return int(v)
    except Exception: return default

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
RIGHT_KEYS = set(list("yuiop[]hjkl;\'bnm,./"))

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
    # 선택: 사람이 읽기 쉬운 보조 필드
    # rec["label_text"] = LABEL_NAME[label_int]

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
            # _keyboard_loop 내부 분기 교체
            if c in LEFT_KEYS:
                _write_label(1)   # 물체 있음
            elif c in RIGHT_KEYS:
                _write_label(0)   # 물체 없음
    finally:
        _kb_restore()

# ---------- 서버 퍼블리셔(서버 모드에서만) ----------
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

# ---------- 로컬 클라이언트 ----------
local_client = None

def on_local_connect(client, userdata, flags, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 성공 (rc={rc})")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)
    print(f"[{get_timestamp()}] 구독 토픽: {LOCAL_TOPIC_SUB}")
    client.publish(GATEWAY_STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[{get_timestamp()}] [상태] 게이트웨이 online 발행: {GATEWAY_STATUS_TOPIC}")

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

    if sensor_id and ultrasonic is not None and MODE == "server":
        payload = {"sensor_id": sensor_id, "ultrasonic": ultrasonic}
        res = server_client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
        if res.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"\n[실패] 서버 전송 실패 (rc={res.rc})")

    if sensor_id in latest and ultrasonic is not None:
        latest[sensor_id] = ultrasonic
        _print_summary()

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
    print(f"  요양원 ID: {NH_ID}")
    print(f"  방 ID: {ROOM_ID}")
    if MODE == "server":
        print(f"  서버: {SERVER_HOST}:{MQTT_PORT}")
    print(f"  로컬 브로커: {LOCAL_BROKER}:{LOCAL_PORT}")
    print("="*60 + "\n")

    _init_summary_area()

    if MODE == "labeling":
        # 비차단 루프 + 키보드 스레드
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
