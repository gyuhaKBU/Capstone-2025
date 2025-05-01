import paho.mqtt.client as mqtt
import ssl
import json
import time
from datetime import datetime
import pytz

# 설정
THING_NAME = "inst001-pi0001-p1002"
CLIENT_ID = "SHADOW_" + THING_NAME
LOCAL_BROKER = "localhost"
LOCAL_PORT = 1883
LOCAL_TOPIC_SUB = "esp/sensor"
LOCAL_TOPIC_PUB = "esp/ack"

AWS_ENDPOINT = "a2fplhkzmgtx9q-ats.iot.ap-northeast-2.amazonaws.com"
CA = "/home/capstone/Desktop/capstone/py/aws-iot-certs/AmazonRootCA1.pem"
CERT = "/home/capstone/Desktop/capstone/py/aws-iot-certs/36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-certificate.pem.crt"
KEY = "/home/capstone/Desktop/capstone/py/aws-iot-certs/36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-private.pem.key"

SHADOW_UPDATE = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"
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
    aws_client.publish(SHADOW_UPDATE, json.dumps(payload), qos=1)
    print("[AWS 전송]", payload)

# 로컬 브로커 수신

def on_local_connect(client, userdata, flags, rc):
    print("[로컬] 연결 상태:", rc)
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)

def on_local_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        print(f"[수신] {data}")

        # ACK 발행
        ack_msg = json.dumps({"status": "received"})
        local_client.publish(LOCAL_TOPIC_PUB, ack_msg)
        print(f"[발신] ACK 전송: {ack_msg}")

        # AWS로 전송
        entity_key = to_entity_key(THING_NAME)
        update_shadow_to_aws(entity_key, data)

    except Exception as e:
        print("[수신 파싱 실패]", e)

# 로컬 MQTT 설정
local_client = mqtt.Client()
local_client.on_connect = on_local_connect
local_client.on_message = on_local_message
local_client.connect(LOCAL_BROKER, LOCAL_PORT, 60)

# AWS MQTT 설정
aws_client = mqtt.Client(client_id=CLIENT_ID)
aws_client.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLSv1_2)
aws_client.connect(AWS_ENDPOINT, 8883, 60)

# 루프 실행
aws_client.loop_start()
local_client.loop_forever()
