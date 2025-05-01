import paho.mqtt.client as mqtt
import json

# 브로커 설정
MQTT_BROKER = "localhost"     # 라즈베리파이 자체 브로커
MQTT_PORT = 1883
MQTT_TOPIC = "esp/sensor"     # ESP에서 발행하는 토픽

# 메시지 수신 시 처리
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        print(f"[수신] call: {data['call']}, fall: {data['fall']}, ultraSonic: {data['ultraSonic']}")
    except Exception as e:
        print("파싱 실패:", e)

# MQTT 연결 시 호출
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT 연결 성공")
        client.subscribe(MQTT_TOPIC)
    else:
        print("MQTT 연결 실패, 코드:", rc)

# 클라이언트 설정
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()
