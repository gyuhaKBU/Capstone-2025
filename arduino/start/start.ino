/*  ------------------------------------------------- 전처리기 ---------------------
 * ---------------------------- 
 */
// 보드 고유 ID #define nursinghome_id "inst001"  요양기관 ID (일단 사용 안함)
#define room_id "301A" // 방 번호
#define bed_id "B"
#define sensor_id "ESP8266-15"

#include <ESP8266WiFi.h> 
#include <PubSubClient.h> 
#include <ArduinoJson.h> 
#define TRIG_PIN D1 // 초음파 쏴
#define ECHO_PIN D2 // 초음파 받아
#define LED_PIN D3 // led
#define BTN_PIN D5 // 푸시버튼

/* ------------------------------------------------- 상수 ------------------------------------------------- */
const char * GATEWAY_STATUS_TOPIC = "gateway/" bed_id "/" sensor_id "/status"; // 라즈베리파이 상태 토픽

/* ------------------------------------------------- 전역 함수 선언 ------------------------------------------------- */

void setup_wifi();
void reconnect();
void callback(char * topic, byte * payload, unsigned int length);
void IRAM_ATTR onButtonPressed(); //버튼 인터럽트
long readUltrasonicDistance();

/*  ------------------------------------------------- 전역 변수 --------------------
 * ----------------------------- 
 */

// WiFi 설정
const char * ssid = room_id;
const char * password = "pi123456";
const char * mqtt_server = "192.168.4.1";

WiFiClient espClient;
PubSubClient client(espClient);
bool gatewayAlive = false; // 게이트웨이 실행 상태 감지

// 토픽 버퍼
char topicSensor[64];
char topicAck[64];

// 멀티태스킹 unsigned long previous_button_debounce = 0;
unsigned long previous_ledOn = 0;
unsigned long previous_sendSensor = 0;
unsigned long previous_readSensor = 0;

// const unsigned long cycle_button_debounce = 15;     디바운싱 샘플 주기 (ms)
const unsigned long cycle_ledOn = 1000; // LED 켜지는 시간 (ms)
const unsigned long cycle_readSensor = 1000; // 센서 읽기 주기 (ms)
const unsigned long cycle_sendSensor = 1000; // 센서 읽고 전송 주기 (ms)

// 버튼 인터럽트
volatile bool btn_pressed = false;
volatile unsigned long lastDebounce = 0;
const unsigned long DEBOUNCE_MS = 50;
// bool lastButtonReading = HIGH; bool buttonState       = HIGH; bool
// btn_pressed       = false; unsigned long lastDebounceTime = 0; led
bool ledOn = false;

//초음파 센서 데이터 전송 판단
bool ultrasonic_upOrDown = false;
const int ultrasonic_TH = 30; // 판단 값
const int ultrasonic_HIGH_TH = ultrasonic_TH + 5;
const int ultrasonic_LOW_TH = ultrasonic_TH - 5;

/*  ------------------------------------------------- 셋업 함수 --------------------
 * ----------------------------- 
 */
void setup() {
    Serial.begin(115200);

    randomSeed(analogRead(A0)); //부팅마다 다른 시드로 동작

    // WiFi 연결
    setup_wifi();

    // MQTT 초기화
    client.setServer(mqtt_server, 1883);
    client.setCallback(callback);

    // 토픽 생성
    snprintf(topicSensor, sizeof(topicSensor), "esp/%s/%s/data", bed_id, sensor_id);
    snprintf(topicAck, sizeof(topicAck), "esp/%s/%s/ack", bed_id, sensor_id);

    // ACK 토픽 구독
    client.subscribe(topicAck, 1);
    // 게이트웨이 상태 토픽 구독
    client.subscribe(GATEWAY_STATUS_TOPIC, 1);

    // 네트워크 정보 출력
    Serial.print("연결된 WiFi SSID: ");
    Serial.println(WiFi.SSID());
    Serial.print("My IP: ");
    Serial.println(WiFi.localIP());

    // 핀 설정
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(LED_PIN, OUTPUT);
    pinMode(BTN_PIN, INPUT_PULLUP);

    // LED 초기 상태 OFF
    digitalWrite(LED_PIN, LOW);

    //버튼 인터럽트
    attachInterrupt(digitalPinToInterrupt(BTN_PIN), onButtonPressed, FALLING);
}

/*  ------------------------------------------------- 루프 함수 --------------------
 * ----------------------------- 
 */
void loop() {
    unsigned long currentMillis = millis();

    // MQTT 연결 유지
    if (!client.connected()) {
        reconnect();
    }
    client.loop();

    // LED 제어 - 1초 후 자동 꺼짐
    if (ledOn && (currentMillis - previous_ledOn >= cycle_ledOn)) {
        ledOn = false;
        digitalWrite(LED_PIN, LOW);
        Serial.println(F("[LED] OFF"));
    }

    if (currentMillis - previous_readSensor >= cycle_readSensor) {
        previous_readSensor = currentMillis;

        // 센서값 읽기
        long ultrasonic = readUltrasonicDistance();
        int call_button = btn_pressed
            ? 1
            : 0;

        // 임계/크로싱 계산
        bool ultrasonic_nowAbove = ultrasonic_upOrDown;
        bool ultrasonic_crossed = false;
        if (ultrasonic >= 0) {
            ultrasonic_nowAbove = (ultrasonic >= ultrasonic_HIGH_TH)
                ? true
                : (ultrasonic <= ultrasonic_LOW_TH)
                    ? false
                    : ultrasonic_upOrDown;
            ultrasonic_crossed = (ultrasonic_nowAbove != ultrasonic_upOrDown);
        }
        int fall_event = ultrasonic_nowAbove
            ? 1
            : 0; // far=1, near=0

        // 발행
        if ((call_button/*|| fall_event*/
        || ultrasonic_crossed) && (currentMillis - previous_sendSensor >= cycle_sendSensor)) {
            previous_sendSensor = currentMillis;
            ultrasonic_upOrDown = ultrasonic_nowAbove;
            if (btn_pressed) 
                btn_pressed = false;
            
            StaticJsonDocument < 128 > doc;
            doc["call_button"] = (call_button != 0);
            doc["fall_event"] = (fall_event != 0);
            doc["ultrasonic"] = ultrasonic;
            char buffer[128];
            serializeJson(doc, buffer);

            bool ok = client.publish(topicSensor, buffer);
            if (ok) {
                ledOn = true;
                previous_ledOn = currentMillis;
                digitalWrite(LED_PIN, HIGH);
            } else {
                Serial.println(F("Publish failed"));
            }
            Serial.println(buffer);
        }
    }
}

/*  ------------------------------------------------- 기타 함수 --------------------
 * ----------------------------- 
 */

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
            Serial.print("실패, rc=");
            Serial.println(client.state());
            delay(2000);
        }
    }
}

void callback(char * topic, byte * payload, unsigned int length) {
    String msg;
    for (unsigned int i = 0; i < length; i++) 
        msg += (char)payload[i];
    
    if (strcmp(topic, topicAck) == 0) {
        // ACK 콜백 (필요 시 추가 처리)
        Serial.println(F("[콜백] ACK 수신"));
    } else if (String(topic) == GATEWAY_STATUS_TOPIC) {
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
        btn_pressed = true;
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