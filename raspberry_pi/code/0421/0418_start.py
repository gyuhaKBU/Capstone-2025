import paho.mqtt.client as mqtt
import ssl
import json
import time
import random

# ==== 설정 ====
ENDPOINT = "a2m262usow07hn-ats.iot.ap-northeast-2.amazonaws.com"
THING_NAME = "inst001-pi0001-p1002"
CLIENT_ID = THING_NAME

# 인증서 경로
CERT_PATH = "/home/capstone/aws-iot-certs/"

CA = CERT_PATH + "AmazonRootCA1.pem"
CERT = CERT_PATH + "04373bbf4f801f169ce1ffadffb37419ee0009f0630740774bf3dc91c8ebd18a-certificate.pem.crt"
KEY = CERT_PATH + "04373bbf4f801f169ce1ffadffb37419ee0009f0630740774bf3dc91c8ebd18a-private.pem.key"

# MQTT 토픽
SHADOW_UPDATE = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"
SHADOW_GET    = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/get"
SHADOW_DELTA  = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update/delta"


# ==== 콜백 함수 ====
def on_connect(client, userdata, flags, rc):
    print("MQTT 연결 상태:", rc)
    client.subscribe(SHADOW_DELTA)
    client.subscribe(SHADOW_GET)


def on_message(client, userdata, msg):
    if msg.topic.endswith("update/delta"):
        payload = json.loads(msg.payload.decode())
        desired_raw = payload.get("state", {})  # 이게 delta 상태 전체
        
        desired = desired_raw.get("desired", desired_raw)  # 중첩 방지 처리

        print("[desired] 상태 변경 요청:", desired)

        if "led" in desired:
            if desired["led"] == "on":
                print("LED ON")
            else:
                print("LED OFF")

        # 상태 동기화
        client.publish(SHADOW_UPDATE, json.dumps({
            "state": {
                "reported": desired
            }
        }))


# ==== Shadow 상태 업데이트 함수 ====
def update_shadow(state_dict):
    payload = {
        "state": {
            "reported": state_dict
        }
    }
    client.publish(SHADOW_UPDATE, json.dumps(payload))
    print("[reported] 상태 전송:", state_dict)


# ==== MQTT 클라이언트 설정 ====
client = mqtt.Client(client_id=CLIENT_ID)
client.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLSv1_2)
client.on_connect = on_connect
client.on_message = on_message

client.connect(ENDPOINT, 8883, 60)

# ==== 실행 루프 ====
client.loop_start()

try:
    while True:
        # 센서 값 생성
        ultraSonic = random.randint(90, 120)
        fall = random.randint(0, 1)  # 0 or 1
        call = random.randint(0, 1)  # 0 or 1

        # Shadow 업데이트
        update_shadow({
            "fall": fall,
            "call": call,
            "ultraSonic": ultraSonic
        })

        time.sleep(10)

except KeyboardInterrupt:
    print("종료됨")
    client.loop_stop()
    client.disconnect()
