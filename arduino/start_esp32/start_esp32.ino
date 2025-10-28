#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>           // 추가


/*  ------------------------------------------------- 전처리기 ---------------------
 * ---------------------------- 
 */
#define room_id "301A" // 방 id
#define bed_id "A" // 침대 id
#define sensor_id "ESP32-4" // 센서 id


// [핀 매크로]
// {HC-SR04 초음파 센서}
#define TRIG_PIN 27
#define ECHO_PIN 33

#define LED_PIN 2 // led

#define BTN_PIN 25 // 푸시버튼

// {TF-Luna 라이다 센서 UART2}
static const int LIDAR_RX_PIN = 16;  // TF-Luna TX -> ESP32 RX2
static const int LIDAR_TX_PIN = -1;  // 연결 불필요


/* ------------------------------------------------- 상수 ------------------------------------------------- */
const char* GATEWAY_STATUS_TOPIC = "gateway/" room_id "/status";



/* ------------------- 전역함수 선언 ------------------- */
// 와이파이
void setup_wifi();
void callback(char* topic, byte* payload, unsigned int length);
void reconnect();

// INPUT
void IRAM_ATTR onButtonPressed(); //버튼 인터럽트
long readUltrasonicDistance(); // 초음파 센서
bool readTFLuna(uint16_t &distance_cm, uint16_t &strength, float &temp_c); // TF-Luna 프레임 파싱

/* ------------------- 전역 객체 선언 ------------------- */
HardwareSerial LidarSerial(2); // TF-Luna UART2

/* ------------------- 전역 변수 ------------------- */

// 와이파이 설정
const char* ssid = room_id;
const char* password = "pi123456";
const char* mqtt_server = "192.168.4.1";
WiFiClient espClient;
PubSubClient client(espClient);

// 토픽 버퍼
char topicSensor[64];
char topicAck[64];
bool gatewayAlive = false;
unsigned long lastGatewaySeen=0;
const unsigned long GATEWAY_TIMEOUT=7000; // 7s

// 멀티태스킹 
unsigned long previous_ledOn = 0;
unsigned long previous_sendSensor = 0;
unsigned long previous_readSensor = 0;
// 멀티태스킹 주기
const unsigned long cycle_ledOn = 500; // LED 켜지는 시간 (ms)
const unsigned long cycle_readSensor = 2000; // 센서 읽기 주기 (ms)
const unsigned long cycle_sendSensor = 3000; // 센서 읽고 전송 주기 (ms)

// 버튼 인터럽트
volatile bool btn_pressed = false;
volatile unsigned long lastDebounce = 0;
const unsigned long DEBOUNCE_MS = 50;
// bool lastButtonReading = HIGH; 
unsigned long lastDebounceTime = 0;
bool ledOn = false;

//초음파 센서 데이터 전송 판단
bool ultrasonic_upOrDown = false;
const int ultrasonic_TH = 30; // 판단 값
const int ultrasonic_HIGH_TH = ultrasonic_TH + 5;
const int ultrasonic_LOW_TH = ultrasonic_TH - 5;

// 초음파 파라미터
static const unsigned long US_TIMEOUT_US = 30000; // ~5m
static const float SOUND_CM_PER_US = 0.0343f;     // 왕복 전파속도 환산용

// 최근 라이다 거리값 유지
volatile uint16_t lastLidarCm = 0;
volatile bool lidarSeen = false;


/* ------------------- 셋업 함수 ------------------- */
void setup() {
  Serial.begin(115200);

  // WiFi 연결
  setup_wifi();

  // MQTT 초기화
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // 토픽 생성
  snprintf(topicSensor, sizeof(topicSensor), "esp/%s/%s/data", bed_id, sensor_id);
  snprintf(topicAck, sizeof(topicAck), "esp/%s/%s/ack", bed_id, sensor_id);

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

  // TF-Luna 시리얼 시작
  LidarSerial.begin(115200, SERIAL_8N1, LIDAR_RX_PIN, LIDAR_TX_PIN);
}

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

      // 라이다 프레임 소거 및 최신값 유지
      uint16_t d, s; float tc;
      if (readTFLuna(d, s, tc)) {
        if (d > 0){
          lastLidarCm = d;
          lidarSeen = true;
        }
      }

      uint16_t lidar_cm = lidarSeen ? lastLidarCm : 0;

      if (millis()-lastGatewaySeen > GATEWAY_TIMEOUT) gatewayAlive=false;

      // 발행
      if (/*(call_button || ultrasonic_crossed) && */
      gatewayAlive &&
      (currentMillis - previous_sendSensor >= cycle_sendSensor)) {
          previous_sendSensor = currentMillis;
          ultrasonic_upOrDown = ultrasonic_nowAbove;
          if (btn_pressed) 
              btn_pressed = false;
          
          StaticJsonDocument < 192 > doc;
          doc["call_button"] = (call_button != 0);
          doc["ultrasonic"] = ultrasonic;
          if (lidarSeen) doc["lidar"] = lastLidarCm;   // 유효할 때만 포함
          char buffer[192];
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


/* ------------------- 함수 ------------------- */

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(true,true);
  delay(500);
  WiFi.begin(ssid, password);

  // 스캔 로그로 SSID 보이는지 확인
  int n=WiFi.scanNetworks();
  for(int i=0;i<n;i++){
    Serial.printf("%s ch=%d rssi=%d enc=%d\n",
      WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i),
      WiFi.encryptionType(i));
    }

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  randomSeed(micros());
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());
}


void callback(char* topic, byte* payload, unsigned int length) {
  String msg; msg.reserve(length);
  for (unsigned int i=0;i<length;i++) msg += (char)payload[i];

  if (strcmp(topic, GATEWAY_STATUS_TOPIC)==0){
    if (msg=="online"){ gatewayAlive=true; lastGatewaySeen=millis(); Serial.println(F("[상태] 게이트웨이 온라인")); }
    else if (msg=="offline"){ gatewayAlive=false; Serial.println(F("[상태] 게이트웨이 오프라인")); }
    return;
  }
  if (strcmp(topic, topicAck)==0) {
    lastGatewaySeen=millis();  // ACK 받을 때마다 갱신
    gatewayAlive=true;          // 연결 상태 유지
    Serial.println(F("[콜백] ACK 수신"));
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("Attempting MQTT connection...");
    String clientId = "ESP32-"; clientId += String(random(0xffff), HEX);
    if (client.connect(clientId.c_str())) {
      Serial.println("connected");
      client.subscribe(topicAck, 1);                 // 이동
      client.subscribe(GATEWAY_STATUS_TOPIC, 1);     // 이동
    } else {
      Serial.print("failed, rc="); Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000);
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

bool readTFLuna(uint16_t &distance_cm, uint16_t &strength, float &temp_c) {
  static uint8_t buf[9];
  while (LidarSerial.available() >= 1) {
    if (LidarSerial.peek() == 0x59) {
      if (LidarSerial.available() >= 2) {
        uint8_t h1 = LidarSerial.read();
        uint8_t h2 = LidarSerial.read();
        if (h1 == 0x59 && h2 == 0x59) {
          unsigned long t0 = millis();
          while (LidarSerial.available() < 7) {
            if (millis() - t0 > 20) return false;
          }
          for (int i = 0; i < 7; i++) buf[i] = LidarSerial.read();

          uint8_t sum = 0x59 + 0x59;
          for (int i = 0; i < 6; i++) sum += buf[i];

          if (sum == buf[6]) {
            distance_cm = (uint16_t)buf[1] << 8 | buf[0];
            strength    = (uint16_t)buf[3] << 8 | buf[2];
            int16_t traw = (int16_t)((buf[5] << 8) | buf[4]);
            temp_c = traw / 8.0f - 256.0f;
            return true;
          }
        } else {
          // 동기화 실패 시 쓰레기 1바이트 버림
          // (read 되어 h1,h2 소진됨)
        }
      } else {
        break;
      }
    } else {
      LidarSerial.read(); // 헤더 전 바이트 제거
    }
  }
  return false;
}