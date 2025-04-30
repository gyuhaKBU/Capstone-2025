import paho.mqtt.client as mqtt
import ssl
import json
import time
import random
from datetime import datetime
import pytz


# ==== 설정 ====
ENDPOINT = "a2fplhkzmgtx9q-ats.iot.ap-northeast-2.amazonaws.com"
THING_NAME = "inst001-pi0001-p1002"
CLIENT_ID = "SHADOW_" + THING_NAME

# 인증서 경로
CERT_PATH = "/home/capstone/Desktop/capstone/py/aws-iot-certs/"

CA   = CERT_PATH + "AmazonRootCA1.pem"
CERT = CERT_PATH + "36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-certificate.pem.crt"
KEY  = CERT_PATH + "36ed8303472d8d26e4ebc6c6538331c5c0e01cf881d16d5c6eb043cda78962de-private.pem.key"

# MQTT 토픽
SHADOW_UPDATE = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"
SHADOW_GET    = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/get"
SHADOW_DELTA  = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update/delta"

# ==== timestamp setting ====
kst = pytz.timezone("Asia/Seoul")

# ==== entityKey 생성 함수 ====
def to_entity_key(thing_name: str) -> str:
    return thing_name.replace("-", "#")

# ==== 콜백 함수 ====
def on_connect(client, userdata, flags, rc):
    print("MQTT 연결 상태:", rc)
    client.subscribe(SHADOW_DELTA)
    client.subscribe(SHADOW_GET)

def on_message(client, userdata, msg):
    if msg.topic.endswith("update/delta"):
        payload = json.loads(msg.payload.decode())
        desired_raw = payload.get("state", {})
        desired = desired_raw.get("desired", desired_raw)

        print("[desired] 상태 변경 요청:", desired)

        if "led" in desired:
            print("LED ON" if desired["led"] == "on" else "LED OFF")

        client.publish(SHADOW_UPDATE, json.dumps({
            "state": {
                "reported": desired
            }
        }))

# ==== Shadow 상태 업데이트 함수 ====
def update_shadow(entity_key, value_data):
    timestamp_str = datetime.now(kst).strftime("%Y-%m-%dT%H:%M:%S.%f")  #ex: '2025-04-23T18:09:44'
    payload = {
        "state": {
            "reported": {
                "entityKey": entity_key,
                "timestamp": timestamp_str,
                "value": value_data
            }
        }
    }
    client.publish(SHADOW_UPDATE, json.dumps(payload))
    print("[reported] 상태 전송:", payload)

# ==== MQTT 클라이언트 설정 ====
client = mqtt.Client(client_id=CLIENT_ID)
client.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLSv1_2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(ENDPOINT, 8883, 60)
client.loop_start()

# ==== 실행 루프 ====
try:
    while True:
        ultraSonic = random.randint(90, 120)
        fall = random.randint(0, 1)
        call = random.randint(0, 1)

        entity_key = to_entity_key(THING_NAME)

        update_shadow(entity_key, {
            "call": call,
            "fall": fall,
            "ultraSonic": ultraSonic
        })

        time.sleep(10)

except KeyboardInterrupt:
    print("종료됨")
    client.loop_stop()
    client.disconnect()
