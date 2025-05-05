# gateway_mqtt_forwarder.py

import paho.mqtt.client as mqtt
import ssl
import json
from datetime import datetime
import pytz

# ——————————————————————————————
# 설정
# ——————————————————————————————
THING_NAME      = "inst001-pi0001"
CLIENT_ID       = "SHADOW_" + THING_NAME

# 로컬 브로커 (Arduino ↔ Pi)
LOCAL_BROKER    = "localhost"
LOCAL_PORT      = 1883
LOCAL_TOPIC_SUB = "esp/+/sensor"         # 모든 환자 단말의 sensor 토픽 구독

# AWS IoT Core
AWS_ENDPOINT    = "a2fplhkzmgtx9q-ats.iot.ap-northeast-2.amazonaws.com"
CA_CERT         = "/home/capstone/Desktop/capstone/py/aws-iot-certs/AmazonRootCA1.pem"
CERT_FILE       = "/home/capstone/Desktop/capstone/py/aws-iot-certs/36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-certificate.pem.crt"
KEY_FILE        = "/home/capstone/Desktop/capstone/py/aws-iot-certs/36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-private.pem.key"
SHADOW_UPDATE   = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"

kst = pytz.timezone("Asia/Seoul")

# 최초 retained 메시지 무시용 플래그
ignore_retained = True

# ——————————————————————————————
# AWS Shadow 업데이트 함수
# ——————————————————————————————
def update_shadow_to_aws(entity_key, value_data):
    timestamp_str = datetime.now(kst).strftime("%Y-%m-%dT%H:%M:%S.%f")
    payload = {
        "state": {
            "reported": {
                "entityKey": entity_key,
                "timestamp": timestamp_str,
                "value": value_data
            }
        }
    }
    aws_client.publish(SHADOW_UPDATE, json.dumps(payload), qos=1)
    print("[AWS 전송]", json.dumps(payload))

# ——————————————————————————————
# 로컬 브로커 콜백: 연결
# ——————————————————————————————
def on_local_connect(client, userdata, flags, rc):
    print(f"[로컬] 연결 상태: {rc}")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)

# ——————————————————————————————
# 로컬 브로커 콜백: 메시지 수신
# ——————————————————————————————
def on_local_message(client, userdata, msg):
    global ignore_retained
    # 첫 번째 retained 메시지 무시
    if ignore_retained and msg.retain:
        print("[로컬] 초기 retained 메시지 무시됨")
        return
    ignore_retained = False

    try:
        payload = msg.payload.decode('utf-8')
        data    = json.loads(payload)
        print(f"[수신] topic={msg.topic} payload={data}")

        # 토픽 구조: "esp/{patient_id}/sensor"
        patient_id = msg.topic.split('/')[1]

        # 1) ACK 발행: esp/{patient_id}/ack
        ack_topic = f"esp/{patient_id}/ack"
        ack_msg   = json.dumps({"status":"received"})
        local_client.publish(ack_topic, ack_msg, qos=1)
        print(f"[발신] ACK → {ack_topic}: {ack_msg}")

        # 2) AWS 전송: entity_key = inst#pi#patient
        inst, pi = THING_NAME.split('-', 1)
        entity_key = f"{inst}#{pi}#{patient_id}"
        update_shadow_to_aws(entity_key, data)

    except Exception as e:
        print("[수신 파싱 실패]", e)

# ——————————————————————————————
# 클라이언트 초기화 및 연결
# ——————————————————————————————
# 로컬 MQTT 클라이언트 (Arduino ↔ Pi)
local_client = mqtt.Client()
local_client.on_connect = on_local_connect
local_client.on_message = on_local_message
local_client.connect(LOCAL_BROKER, LOCAL_PORT, keepalive=60)

# AWS IoT Core MQTT 클라이언트
aws_client = mqtt.Client(client_id=CLIENT_ID)
aws_client.tls_set(ca_certs=CA_CERT,
                   certfile=CERT_FILE,
                   keyfile=KEY_FILE,
                   tls_version=ssl.PROTOCOL_TLSv1_2)
aws_client.connect(AWS_ENDPOINT, 8883, keepalive=60)

# ——————————————————————————————
# 메인 루프 실행
# ——————————————————————————————
aws_client.loop_start()
local_client.loop_forever()