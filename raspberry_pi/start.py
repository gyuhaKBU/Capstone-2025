import paho.mqtt.client as mqtt
import ssl
import json
import time
from datetime import datetime
import pytz

# ==== AWS IoT 설정 ====
AWS_ENDPOINT = "a2fplhkzmgtx9q-ats.iot.ap-northeast-2.amazonaws.com"
THING_NAME = "inst001-pi0001-p1002"
CLIENT_ID = "SHADOW_" + THING_NAME

# 인증서 경로
CERT_PATH = "/home/capstone/Desktop/capstone/py/aws-iot-certs/"
CA   = CERT_PATH + "AmazonRootCA1.pem"
CERT = CERT_PATH + "36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-certificate.pem.crt"
KEY  = CERT_PATH + "36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-private.pem.key"

# MQTT 토픽 (AWS)
SHADOW_UPDATE = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"

# ==== 로컬 브로커 설정 (ESP 수신용) ====
LOCAL_BROKER = "localhost"
LOCAL_PORT = 1883
LOCAL_TOPIC = "esp/sensor"

# ==== timestamp 세팅 ====
kst = pytz.timezone("Asia/Seoul")

def to_entity_key(thing_name: str) -> str:
    return thing_name.replace("-", "#")

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
    aws_client.publish(SHADOW_UPDATE, json.dumps(payload))
    print("[AWS 전송]", payload)

# ==== 로컬 MQTT 수신 콜백 ====
def on_local_connect(client, userdata, flags, rc):
    print("로컬 MQTT 연결 상태:", rc)
    client.subscribe(LOCAL_TOPIC)

def on_local_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        print(f"[수신] call: {data['call']}, fall: {data['fall']}, ultraSonic: {data['ultraSonic']}")
        entity_key = to_entity_key(THING_NAME)
        update_shadow_to_aws(entity_key, data)
    except Exception as e:
        print("[파싱 실패]", e)

# ==== AWS MQTT 설정 ====
aws_client = mqtt.Client(client_id=CLIENT_ID)
aws_client.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLSv1_2)
aws_client.connect(AWS_ENDPOINT, 8883, 60)
aws_client.loop_start()

# ==== 로컬 MQTT 클라이언트 설정 ====
local_client = mqtt.Client()
local_client.on_connect = on_local_connect
local_client.on_message = on_local_message
local_client.connect(LOCAL_BROKER, LOCAL_PORT, 60)
local_client.loop_forever()
