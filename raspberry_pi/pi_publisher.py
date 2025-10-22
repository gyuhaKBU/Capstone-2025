# /home/capstone/iot/pi_bridge.py
#!/usr/bin/env python3
# ============================
NH_ID       = "NH-001"            # 요양원 ID
ROOM_ID     = "301A"              # 방 ID
SERVER_HOST = "121.78.128.175"    # 서버 IP/도메인
MQTT_PORT   = 8883                # 1883(평문) | 8883(TLS)
# ============================

TOPIC = "pi/"+NH_ID+"/"+ROOM_ID+"/data"   # 서버로 보낼 토픽
LOCAL_TOPIC_SUB = "esp/+/+/data"          # esp/{bed_id}/{sensor_id}/data
GATEWAY_STATUS_TOPIC = "gateway/" + ROOM_ID + "/status"
ignore_retained = True

# 로컬 브로커(라즈베리파이)
LOCAL_BROKER = "localhost"
LOCAL_PORT   = 1883

# 서버 TLS 인증서(8883에서 필요)
CA_FILE   = "/home/capstone/Desktop/certs/ca.crt"
CERT_FILE = "/home/capstone/Desktop/certs/client.crt"
KEY_FILE  = "/home/capstone/Desktop/certs/client.key"

import json, ssl, signal, sys
from datetime import datetime
from paho.mqtt import client as mqtt

def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default

def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}

def get_timestamp():
    """현재 시간을 문자열로 반환"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 서버 퍼블리셔(지속 연결)
server_client = mqtt.Client(protocol=mqtt.MQTTv311)
if MQTT_PORT == 8883:
    server_client.tls_set(
        ca_certs=CA_FILE,
        certfile=CERT_FILE,
        keyfile=KEY_FILE,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
server_client.connect(SERVER_HOST, MQTT_PORT, keepalive=60)
server_client.loop_start()
print(f"[{get_timestamp()}] 서버 연결 완료: {SERVER_HOST}:{MQTT_PORT}")

# 로컬 클라이언트 전역 변수 (signal handler에서 접근 위해)
local_client = None

# ——— 로컬 브로커 콜백 ———
def on_local_connect(client, userdata, flags, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 성공 (rc={rc})")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)
    print(f"[{get_timestamp()}] 구독 토픽: {LOCAL_TOPIC_SUB}")
    
    # 연결 성공 시 게이트웨이 online 상태 발행
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
        print(f"[오류] JSON 파싱 실패: {e}")
        return

    parts = msg.topic.split("/")  # esp/{bed_id}/{sensor_id}/data
    if len(parts) < 4:
        print(f"[오류] 토픽 형식 오류")
        return
    bed_id, sensor_id = parts[1], parts[2]

    payload = _drop_none({
        # NH_ID, ROOM_ID는 토픽에 포함되므로 생략
        "bed_id":      bed_id,
        "sensor_id":   data.get("sensor_id") or sensor_id,
        "call_button": _as_int(data.get("call_button", 0), 0),
        "fall_event":  _as_int(data.get("fall_event", 0), 0),
        "ultrasonic":  _as_int(data.get("ultrasonic")),
    })

    # 간결한 출력
    print("-" * 85)
    print(f"[수신] {sensor_id} : {msg.payload.decode('utf-8')}")
    print(f"[송신] {json.dumps(payload, ensure_ascii=False)}")
    
    result = server_client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        print(f"[실패] 서버 전송 실패 (rc={result.rc})")

    # ACK 전송
    ack_topic = f"esp/{bed_id}/{sensor_id}/ack"
    ack_payload = {"status": "received"}
    client.publish(ack_topic, json.dumps(ack_payload), qos=1, retain=False)

def on_local_disconnect(client, userdata, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 해제 (rc={rc})")

# 종료 시그널 핸들러
def signal_handler(sig, frame):
    timestamp = get_timestamp()
    print(f"\n[{timestamp}] 프로그램 종료 중...")
    if local_client:
        # 종료 전 게이트웨이 offline 상태 발행
        local_client.publish(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
        print(f"[{timestamp}] [상태] 게이트웨이 offline 발행: {GATEWAY_STATUS_TOPIC}")
        local_client.disconnect()
    server_client.loop_stop()
    server_client.disconnect()
    print(f"[{timestamp}] 종료 완료")
    sys.exit(0)

def main():
    global local_client
    
    # SIGINT(Ctrl+C) 핸들러 등록
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    local_client = mqtt.Client()
    
    # Last Will 설정: 비정상 종료 시 자동으로 offline 발행
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