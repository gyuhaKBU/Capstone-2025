// ESP32S + 초음파(HC-SR04 타입) + TF-Luna(UART) 1Hz 출력 + 버튼(25) 누르는 동안 LED(2) ON

#include <HardwareSerial.h>

// 핀 설정
#define TRIG_PIN 27
#define ECHO_PIN 33
#define LED_PIN  2
#define BTN_PIN  25

// TF-Luna UART2
static const int LIDAR_RX_PIN = 16;  // TF-Luna TX -> ESP32 RX2
static const int LIDAR_TX_PIN = 17;  // 연결 불필요
HardwareSerial LidarSerial(2);

// 초음파 파라미터
static const unsigned long US_TIMEOUT_US = 30000; // ~5m
static const float SOUND_CM_PER_US = 0.0343f;     // 왕복 전파속도 환산용

// 최근 라이다 거리값 유지
volatile uint16_t lastLidarCm = 0;
volatile bool lidarSeen = false;

// TF-Luna 프레임 파싱
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

// 초음파 거리(cm)
uint16_t readUltrasonicCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long dur = pulseIn(ECHO_PIN, HIGH, US_TIMEOUT_US);
  if (dur == 0) return 0; // 타임아웃
  float cm = (dur * SOUND_CM_PER_US) * 0.5f;
  if (cm < 0) cm = 0;
  if (cm > 500) cm = 500; // 안전 클램프
  return (uint16_t)(cm + 0.5f);
}

void setup() {
  Serial.begin(115200);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  pinMode(BTN_PIN, INPUT_PULLUP);

  digitalWrite(LED_PIN, LOW);

  LidarSerial.begin(115200, SERIAL_8N1, LIDAR_RX_PIN, LIDAR_TX_PIN);
}

void loop() {
  // 버튼 동작: 누르는 동안(LOW) LED ON
  digitalWrite(LED_PIN, digitalRead(BTN_PIN) == LOW ? HIGH : LOW);

  // 라이다 프레임 소거 및 최신값 유지
  uint16_t d, s; float tc;
  if (readTFLuna(d, s, tc)) {
    lastLidarCm = d;
    lidarSeen = true;
  }

  // 1Hz 리포트
  static uint32_t tPrev = 0;
  uint32_t now = millis();
  if (now - tPrev >= 1000) {
    tPrev = now;
    uint16_t us_cm = readUltrasonicCm();
    uint16_t lidar_cm = lidarSeen ? lastLidarCm : 0;
    Serial.print("Ultrasonic(cm): ");
    Serial.print(us_cm);
    Serial.print("  Lidar(cm): ");
    Serial.println(lidar_cm);
  }
}
