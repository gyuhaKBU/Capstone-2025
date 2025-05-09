/* ------------------------------------------------- 전처리기 ------------------------------------------------- */
// 보드 고유 ID
#define PATIENT_ID   "p1001"

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define TRIG_PIN D1   // GPIO5 | 초음파 쏴
#define ECHO_PIN D2   // GPIO4 | 초음파 받아
#define BTN_PIN  D5   // GPIO14 | 푸시버튼

/* ------------------------------------------------- 상수 ------------------------------------------------- */
const char* GATEWAY_STATUS_TOPIC = "gateway/inst001-pi0001/status";  // 라즈베리파이 상태 토픽

/* ------------------------------------------------- 전역 변수 ------------------------------------------------- */
// WiFi 설정
const char* ssid        = "inst001-pi0001";
const char* password    = "12345678";
const char* mqtt_server = "192.168.4.1";

WiFiClient espClient;
PubSubClient client(espClient);
bool gatewayAlive = false;  // 게이트웨이 실행 상태 감지

// 토픽 버퍼
char topicSensor[32];
char topicAck[32];

// 멀티태스킹
unsigned long previous_button_debounce = 0;
unsigned long previous_readSendSensor  = 0;
const unsigned long cycle_button_debounce = 15;    // 디바운싱 샘플 주기 (ms)
const unsigned long cycle_readSendSensor  = 5000;  // 센서 읽고 전송 주기 (ms)

// 버튼 디바운스 상태
bool lastButtonReading = HIGH;
bool buttonState       = HIGH;
bool btn_pressed       = false;
unsigned long lastDebounceTime = 0;

/* ------------------------------------------------- 함수 선언 ------------------------------------------------- */
void setup_wifi();
void reconnect();
void callback(char* topic, byte* payload, unsigned int length);
long readUltrasonicDistance();

/* ------------------------------------------------- 셋업 함수 ------------------------------------------------- */
void setup() {
  Serial.begin(115200);

  // WiFi 연결
  setup_wifi();

  // MQTT 초기화
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // 토픽 생성
  snprintf(topicSensor, sizeof(topicSensor), "esp/%s/sensor", PATIENT_ID);
  snprintf(topicAck,    sizeof(topicAck),    "esp/%s/ack",    PATIENT_ID);

  // ACK 토픽 구독
  client.subscribe(topicAck, 1);
  // 게이트웨이 상태 토픽 구독
  client.subscribe(GATEWAY_STATUS_TOPIC, 1);

  // 네트워크 정보 출력
  Serial.print("연결된 WiFi SSID: "); Serial.println(WiFi.SSID());
  Serial.print("My IP: "); Serial.println(WiFi.localIP());

  // 핀 설정
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BTN_PIN, INPUT_PULLUP);
}

/* ------------------------------------------------- 루프 함수 ------------------------------------------------- */
void loop() {
  unsigned long currentMillis = millis();

  // MQTT 연결 유지
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // 버튼 디바운싱
  if (currentMillis - previous_button_debounce >= cycle_button_debounce) {
    previous_button_debounce = currentMillis;
    bool reading = digitalRead(BTN_PIN);
    if (reading != lastButtonReading) {
      lastDebounceTime = currentMillis;
    }
    lastButtonReading = reading;
    if (currentMillis - lastDebounceTime > cycle_button_debounce) {
      if (reading != buttonState) {
        buttonState = reading;
        if (buttonState == LOW) {
          btn_pressed = true;
        }
      }
    }
  }

  // 게이트웨이 온라인 상태에서만 발행
  if (gatewayAlive && (currentMillis - previous_readSendSensor >= cycle_readSendSensor)) {
    previous_readSendSensor = currentMillis;

    // 센서값 읽기
    int call        = btn_pressed ? 1 : 0;
    btn_pressed     = false;
    int fall        = random(0, 2);
    long ultraSonic = readUltrasonicDistance();

    // JSON 패킹
    StaticJsonDocument<128> doc;
    doc["call"]       = call;
    doc["fall"]       = fall;
    doc["ultraSonic"] = ultraSonic;
    char buffer[128];
    serializeJson(doc, buffer);

    // 발행
    bool ok = client.publish(topicSensor, buffer);
    if (!ok) {
      Serial.println(F("Publish failed"));
    } else {
      Serial.print(F("[발행] ")); Serial.println(buffer);
    }
  }
  else if (!gatewayAlive && (currentMillis - previous_readSendSensor >= cycle_readSendSensor)) {
    // 게이트웨이 오프라인 상태 알림 (로그)
    Serial.println(F("[경고] 게이트웨이 오프라인, 발행 중단"));
    // 타이머 갱신으로 지속 경고 방지
    previous_readSendSensor = currentMillis;
  }
}

/* ------------------------------------------------- 기타 함수 ------------------------------------------------- */

void setup_wifi() {
  delay(10);
  Serial.println("WiFi 연결 중...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(200);
    Serial.print('.');
  }
  Serial.println("\nWiFi 연결 완료!");
}

void reconnect() {
  String clientId = "ESP8266-" + String(ESP.getChipId(), HEX);
  while (!client.connected()) {
    Serial.print("MQTT 연결 시도...");
    if (client.connect(clientId.c_str())) {
      Serial.println("연결 성공!");
      // 필요한 토픽 다시 구독
      client.subscribe(topicAck, 1);
      client.subscribe(GATEWAY_STATUS_TOPIC, 1);
      delay(2000);
    } else {
      Serial.print("실패, rc="); Serial.println(client.state());
      delay(2000);
    }
  }
}

void callback(char* topic, byte* payload, unsigned int length) {
  String msg;
  for (unsigned int i=0; i<length; i++) msg += (char)payload[i];

  if (strcmp(topic, topicAck) == 0) {
    // ACK 콜백 (필요 시 추가 처리)
    Serial.println(F("[콜백] ACK 수신"));
  }
  else if (String(topic) == GATEWAY_STATUS_TOPIC) {
    if (msg == "online") {
      gatewayAlive = true;
      Serial.println(F("[상태] 게이트웨이 온라인"));
    } else if (msg == "offline") {
      gatewayAlive = false;
      Serial.println(F("[상태] 게이트웨이 오프라인"));
    }
  }
}

long readUltrasonicDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return -1;
  return duration * 0.034 / 2;
}
