/* ------------------------------------------------- 전처리기 ------------------------------------------------- */
// 보드 고유 ID
#define PATIENT_ID   "p1002"
#define RASPI_ID     "pi0001"
#define INST_ID     "inst001"

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define TRIG_PIN D1   // GPIO5 | 초음파 쏴
#define ECHO_PIN D2   // GPIO4 | 초음파 받아
#define BTN_PIN  D5   // GPIO14 | 푸시버튼

/* ------------------------------------------------- 상수 ------------------------------------------------- */
const char* GATEWAY_STATUS_TOPIC = "gateway/" INST_ID "-" RASPI_ID "/status";  // 라즈베리파이 상태 토픽

/* ------------------------------------------------- 전역 변수 ------------------------------------------------- */
// WiFi 설정
const char* ssid = INST_ID "-" RASPI_ID;
const char* password    = "12345678";
const char* mqtt_server = "192.168.4.1";

WiFiClient espClient;
PubSubClient client(espClient);
bool gatewayAlive = false;  // 게이트웨이 실행 상태 감지

// 토픽 버퍼
char topicSensor[32];
char topicAck[32];

// 멀티태스킹
// unsigned long previous_button_debounce = 0;
unsigned long previous_sendSensor  = 0;
unsigned long previous_readSensor  = 0;

// const unsigned long cycle_button_debounce = 15;    // 디바운싱 샘플 주기 (ms)
const unsigned long cycle_readSensor  = 500;  // 센서 읽기 주기 (ms)
const unsigned long cycle_sendSensor  = 5000;  // 센서 읽고 전송 주기 (ms)

// 버튼 인터럽트
volatile bool btn_pressed = false;
volatile unsigned long lastDebounce = 0;
const unsigned long DEBOUNCE_MS = 50;
// bool lastButtonReading = HIGH;
// bool buttonState       = HIGH;
// bool btn_pressed       = false;
// unsigned long lastDebounceTime = 0;

//초음파 센서 데이터 전송 판단
bool ultraSonic_upOrDown = false;
const int ultraSonic_HIGH_TH = 205;
const int ultraSonic_LOW_TH  = 195;

/* ------------------------------------------------- 함수 선언 ------------------------------------------------- */
void setup_wifi();
void reconnect();
void callback(char* topic, byte* payload, unsigned int length);
void IRAM_ATTR onButtonPressed(); //버튼 인터럽트
long readUltrasonicDistance();

/* ------------------------------------------------- 셋업 함수 ------------------------------------------------- */
void setup() {
  Serial.begin(115200);

  randomSeed(analogRead(A0)); //부팅마다 다른 시드로 동작

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

  //버튼 인터럽트
  attachInterrupt(digitalPinToInterrupt(BTN_PIN),
                  onButtonPressed,
                  FALLING);
}

/* ------------------------------------------------- 루프 함수 ------------------------------------------------- */
void loop() {
  unsigned long currentMillis = millis();

  // MQTT 연결 유지
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // // 버튼 디바운싱
  // if (!btn_pressed && (currentMillis - previous_button_debounce >= cycle_button_debounce)) {
  //   previous_button_debounce = currentMillis;
  //   bool reading = digitalRead(BTN_PIN);
  //   if (reading != lastButtonReading) {
  //     lastDebounceTime = currentMillis;
  //   }
  //   lastButtonReading = reading;
  //   if (currentMillis - lastDebounceTime > cycle_button_debounce) {
  //     if (reading != buttonState) {
  //       buttonState = reading;
  //       if (buttonState == LOW) {
  //         btn_pressed = true;
  //       }
  //     }
  //   }
  // }

  if (currentMillis - previous_readSensor >= cycle_readSensor) {
    previous_readSensor = currentMillis;

    // 센서값 읽기
    int fall        = (random(1000) == 0) ? 1 : 0;
    long ultraSonic = readUltrasonicDistance();
    int call        = btn_pressed ? 1 : 0;

    bool ultraSonic_nowAbove = ultraSonic >= ultraSonic_HIGH_TH ? true
                              : ultraSonic <= ultraSonic_LOW_TH  ? false
                              : ultraSonic_upOrDown;
    bool ultraSonic_crossed = (ultraSonic_nowAbove != ultraSonic_upOrDown);
      
    // 게이트웨이 온라인 상태에서만 발행
    if(call || fall || ultraSonic_crossed){
      if (gatewayAlive && (currentMillis - previous_sendSensor >= cycle_sendSensor)) {
        previous_sendSensor = currentMillis;
        ultraSonic_upOrDown    = ultraSonic_nowAbove;  // 초음파 전송 상태 업데이트
        if (btn_pressed) {
          btn_pressed = false;
        }

        // JSON 패킹
        StaticJsonDocument<128> doc;
        doc["call"]       = (call != 0);
        doc["fall"]       = (fall != 0);
        doc["ultraSonic"] = ultraSonic;
        char buffer[128];
        serializeJson(doc, buffer);


        // 발행
        bool ok = client.publish(topicSensor, buffer);
        if (!ok)
          Serial.println(F("Publish failed"));
        else
          Serial.print(F("[발행] ")); Serial.println(buffer);
      }
      else if (!gatewayAlive && (currentMillis - previous_sendSensor >= cycle_sendSensor)) {
        // 게이트웨이 오프라인 상태 알림 (로그)
        Serial.println(F("[경고] 게이트웨이 오프라인, 발행 중단"));
        // 타이머 갱신으로 지속 경고 방지
        previous_sendSensor = currentMillis;
      }
    }
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

void IRAM_ATTR onButtonPressed() {
  unsigned long now = millis();
  if (now - lastDebounce > DEBOUNCE_MS) {
    btn_pressed  = true;
    lastDebounce = now;
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
