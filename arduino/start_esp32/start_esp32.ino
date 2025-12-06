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



/* ------------------- 전역 함수 선언 ------------------- */
// 와이파이
void setup_wifi();
void callback(char* topic, byte* payload, unsigned int length);
void reconnect();

// INPUT
void IRAM_ATTR onButtonPressed(); //버튼 인터럽트
long readUltrasonicDistance(); // 초음파 센서
bool readTFLuna(uint16_t &distance_cm, uint16_t &strength, float &temp_c); // TF-Luna 프레임 파싱

// 주기 설정
void set_read_ms(uint16_t ms);
void set_send_ms(uint16_t ms);
void set_period_ms(uint16_t ms);

// 윈도우 필터
static inline int iabs(int x){ return x < 0 ? -x : x; } //
int median_win(); 
int readUltrasonicFiltered(); 

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
char topicCfg[64];  // 설정 토픽 esp/{bed}/{sensor}/cfg
bool gatewayAlive = false;
unsigned long lastGatewaySeen=0;
const unsigned long GATEWAY_TIMEOUT=3000; // 7s

// 멀티태스킹 
unsigned long previous_ledOn = 0;
unsigned long previous_sendSensor = 0;
unsigned long previous_readSensor = 0;
// 멀티태스킹 주기
const unsigned long cycle_ledOn = 50; // LED 켜지는 시간 (ms)
volatile unsigned long cycle_readSensor = 80; // 센서 읽기 주기 (ms)
volatile unsigned long cycle_sendSensor = 200;  // 센서 전소 주기 (ms)

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

// 필터 설정 (윈도우 사이즈)
const int WIN = 3;              // 3 또는 5
const int MIN_CM = 2;           // 유효 하한
int MAX_CM = 51;         // 유효 상한
int MAX_JUMP = 49;        // 한 번에 허용 점프(cm)
int  ringbuf[5];                // 최대 5까지 지원
int  rcount = 0, rpos = 0;
int  smooth_cm = -1;


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
  snprintf(topicCfg, sizeof(topicCfg), "esp/%s/%s/cfg", bed_id, sensor_id);

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

  // 초기 주기 설정
  if (sensor_id == "ESP32-1") set_read_ms(70);
  else if (sensor_id == "ESP32-2") set_read_ms(80);
  else if (sensor_id == "ESP32-3") set_read_ms(90);
  else if (sensor_id == "ESP32-4") set_read_ms(100);
  else set_read_ms(60);
  set_send_ms(200);
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

  if (gatewayAlive && (currentMillis - previous_readSensor >= cycle_readSensor)) {
      previous_readSensor = currentMillis;

      // 센서값 읽기
      long ultrasonic = readUltrasonicFiltered();
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
  if (strcmp(topic, topicCfg) == 0) {
    StaticJsonDocument<96> doc;
    DeserializationError err = deserializeJson(doc, payload, length); // length 사용
    if (!err) {
      if (doc.containsKey("read_ms"))  set_read_ms(doc["read_ms"].as<uint16_t>());
      if (doc.containsKey("send_ms"))  set_send_ms(doc["send_ms"].as<uint16_t>());
      // 선택: Hz 단위도 허용
      if (doc.containsKey("read_hz"))  set_read_ms((uint16_t)max(60, (int)(1000.0 / doc["read_hz"].as<float>())));
      if (doc.containsKey("send_hz"))  set_send_ms((uint16_t)max(50, (int)(1000.0 / doc["send_hz"].as<float>())));
      // 하위호환: period_ms → 전송 주기
      if (doc.containsKey("period_ms")) set_period_ms(doc["period_ms"].as<uint16_t>());
      // ... 기존 send_hz 처리 코드 아래에 추가 ...
      if (doc.containsKey("send_hz"))  set_send_ms((uint16_t)max(50, (int)(1000.0 / doc["send_hz"].as<float>())));

      if (doc.containsKey("max_cm")) {
        MAX_CM = doc["max_cm"].as<int>();
        Serial.printf("[CFG] MAX_CM 변경됨: %d\n", MAX_CM);
      }
      if (doc.containsKey("max_jump")) {
        MAX_JUMP = doc["max_jump"].as<int>();
        Serial.printf("[CFG] MAX_JUMP 변경됨: %d\n", MAX_JUMP);
      }
    } else {
      // 숫자 단독 페이로드도 허용: 전송 주기
      char buf[16]; size_t n = min<size_t>(length, sizeof(buf)-1);
      memcpy(buf, payload, n); buf[n] = 0;
      int ms = atoi(buf);
      if (ms > 0) set_send_ms((uint16_t)ms);
    }
    return;
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
      client.subscribe(topicCfg, 1);                 // 추가
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

void set_read_ms(uint16_t ms) {
  // HC-SR04 최소 여유: 60ms 이상 권장
  ms = constrain(ms, 60, 2000);
  cycle_readSensor = ms;
  Serial.printf("[CFG] read_ms=%u (~%.2f Hz)\n", ms, 1000.0 / ms);
}

void set_send_ms(uint16_t ms) {
  ms = constrain(ms, 50, 5000);
  cycle_sendSensor = ms;
  Serial.printf("[CFG] send_ms=%u (~%.2f Hz)\n", ms, 1000.0 / ms);
}

// 하위호환: period_ms 들어오면 전송 주기만 변경
void set_period_ms(uint16_t ms) {
  set_send_ms(ms);
}

void push_cm(int v){
  ringbuf[rpos] = v;
  rpos = (rpos + 1) % WIN;
  if (rcount < WIN) rcount++;
}

int median_win(){
  int tmp[5];
  // 최근 창 전체 내용 정렬(순서는 상관없음)
  int n = rcount;
  for(int i=0;i<n;i++) tmp[i] = ringbuf[i];
  for(int i=0;i<n-1;i++)
    for(int j=i+1;j<n;j++)
      if (tmp[i] > tmp[j]) { int t=tmp[i]; tmp[i]=tmp[j]; tmp[j]=t; }
  return tmp[n/2];
}

int readUltrasonicFiltered(){
  int raw = (int)readUltrasonicDistance();   // cm, 타임아웃 시 -1

  // 0) 타임아웃은 그대로 -1 반환. 버퍼/평활값 건드리지 않음.
  if (raw == -1) return -1;

  // 1) 범위 밖은 이전값 유지
  if (raw < MIN_CM || raw > MAX_CM) return smooth_cm;

  // 2) 급격 점프 1회 무시(초기엔 허용)
  if (smooth_cm > 0 && abs(raw - smooth_cm) > MAX_JUMP) return smooth_cm;

  // 3) 창 가운데값
  push_cm(raw);
  int med = median_win();

  // 4) 부드럽게 섞기(이전 60% + 새값 40%)
  if (smooth_cm < 0) smooth_cm = med;
  else               smooth_cm = (smooth_cm*6 + med*4) / 10;

  return smooth_cm;
}