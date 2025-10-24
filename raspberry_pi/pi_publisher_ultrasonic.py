#!/usr/bin/env python3
# ============================
NH_ID       = "NH-001"
ROOM_ID     = "301A"
SERVER_HOST = "121.78.128.175"
MQTT_PORT   = 8883
# ============================

TOPIC = f"pi/{NH_ID}/{ROOM_ID}/data"
LOCAL_TOPIC_SUB = "esp/+/+/data"          # esp/{bed_id}/{sensor_id}/data
GATEWAY_STATUS_TOPIC = f"gateway/{ROOM_ID}/status"
ignore_retained = True

LOCAL_BROKER = "localhost"
LOCAL_PORT   = 1883

CA_FILE   = "/home/capstone/Desktop/certs/ca.crt"
CERT_FILE = "/home/capstone/Desktop/certs/client.crt"
KEY_FILE  = "/home/capstone/Desktop/certs/client.key"

import json, ssl, signal, sys
from datetime import datetime
from paho.mqtt import client as mqtt

ORDER = [f"ESP32-{i}" for i in range(1,5)]
latest = {k: None for k in ORDER}

def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default

def _norm_sid(s):
    s = str(s).strip()
    if s.lower().startswith("esp32-"):
        return "ESP32-" + s.split("-",1)[1]
    return s

def _print_summary():
    # 커서를 시작 위치로 이동 후 여러 줄 출력
    lines = [f"{k}: {latest[k] if latest[k] is not None else '-'}" for k in ORDER]
    # 커서를 4줄 위로 이동 (ORDER 길이만큼)
    sys.stdout.write(f"\033[{len(ORDER)}A")
    # 각 줄 출력 (줄 전체를 지우고 새로 씀)
    for line in lines:
        sys.stdout.write(f"\033[K{line}\n")
    sys.stdout.flush()

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 서버 퍼블리셔
server_client = mqtt.Client(protocol=mqtt.MQTTv311)
if MQTT_PORT == 8883:
    server_client.tls_set(
        ca_certs=CA_FILE, certfile=CERT_FILE, keyfile=KEY_FILE,
        cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
server_client.connect(SERVER_HOST, MQTT_PORT, keepalive=60)
server_client.loop_start()
print(f"[{get_timestamp()}] 서버 연결 완료: {SERVER_HOST}:{MQTT_PORT}")

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
    if not sensor_id or ultrasonic is None:
        # 스킵해도 ACK는 보냄(게이트웨이 상태 유지)
        ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
        client.publish(ack_topic, json.dumps({"status": "skipped"}), qos=1, retain=False)
        return

    # 서버 전송
    payload = {"sensor_id": sensor_id, "ultrasonic": ultrasonic}
    res = server_client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
    if res.rc != mqtt.MQTT_ERR_SUCCESS:
        print(f"\n[실패] 서버 전송 실패 (rc={res.rc})")

    # 최신값 갱신 및 요약 출력
    if sensor_id in latest:
        latest[sensor_id] = ultrasonic
    _print_summary()

    # ESP로 ACK
    ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
    client.publish(ack_topic, json.dumps({"status": "received"}), qos=1, retain=False)

def on_local_disconnect(client, userdata, rc):
    print(f"\n[{get_timestamp()}] 로컬 브로커 연결 해제 (rc={rc})")

def signal_handler(sig, frame):
    ts = get_timestamp()
    print(f"\n[{ts}] 프로그램 종료 중...")
    if local_client:
        local_client.publish(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
        print(f"[{ts}] [상태] 게이트웨이 offline 발행: {GATEWAY_STATUS_TOPIC}")
        local_client.disconnect()
    server_client.loop_stop()
    server_client.disconnect()
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
    print(f"  요양원 ID: {NH_ID}")
    print(f"  방 ID: {ROOM_ID}")
    print(f"  서버: {SERVER_HOST}:{MQTT_PORT}")
    print(f"  로컬 브로커: {LOCAL_BROKER}:{LOCAL_PORT}")
    print("="*60 + "\n")

    local_client.loop_forever()

if __name__ == "__main__":
    main()