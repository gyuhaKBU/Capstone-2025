import paho.mqtt.client as mqtt
import ssl

# --- 설정 (자신의 환경에 맞게 수정) ---
BROKER_IP   = "121.78.128.175"
BROKER_PORT = 8883
CLIENT_ID   = "raspberry-pi-tester"

# 방금 라즈베리파이로 복사한 파일들의 경로
CA_CERT   = "/home/capstone/Desktop/certs/ca.crt"
CLIENT_CERT = "/home/capstone/Desktop/certs/client.crt"
CLIENT_KEY  = "/home/capstone/Desktop/certs/client.key"

# --- 콜백 함수 정의 ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ 브로커에 성공적으로 연결되었습니다!")
        # 연결 성공 시 "test/topic"으로 메시지 발행
        client.publish("test/topic", "Hello Secure MQTT from Raspberry Pi!", qos=1)
    else:
        print(f"❌ 연결 실패 (Code: {rc})")
        if rc == 5:
            print("-> 원인: 인증 실패. 인증서 파일 경로와 내용을 확인하세요.")

def on_publish(client, userdata, mid):
    print("✉️ 메시지 발행 완료! (mid: {})".format(mid))
    client.disconnect() # 메시지 발행 후 연결 종료

def on_disconnect(client, userdata, rc):
    print("🔌 연결이 종료되었습니다.")

# --- 메인 코드 ---
# 클라이언트 생성
client = mqtt.Client(client_id=CLIENT_ID)

# 콜백 함수 연결
client.on_connect = on_connect
client.on_publish = on_publish
client.on_disconnect = on_disconnect

# TLS 설정 적용
client.tls_set(ca_certs=CA_CERT,
               certfile=CLIENT_CERT,
               keyfile=CLIENT_KEY,
               tls_version=ssl.PROTOCOL_TLSv1_2)

# 브로커 연결 시도
print(f"{BROKER_IP}:{BROKER_PORT} 로 연결을 시도합니다...")
try:
    client.connect(BROKER_IP, BROKER_PORT, 60)
except Exception as e:
    print(f"🚨 연결 중 오류 발생: {e}")

# 네트워크 루프 시작
client.loop_forever()