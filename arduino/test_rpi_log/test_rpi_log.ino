// ESP32S + 초음파(HC-SR04) + TF-Luna(UART) + 버튼
#include <HardwareSerial.h>

// 핀
#define TRIG_PIN 27
#define ECHO_PIN 33
#define LED_PIN  2
#define BTN_PIN  25

// TF-Luna UART2 (센서 TX->16, 센서 RX 미사용)
static const int LIDAR_RX_PIN = 16;
static const int LIDAR_TX_PIN = 17;
HardwareSerial LidarSerial(2);

static const unsigned long US_TIMEOUT_US = 30000;
static const float SOUND_CM_PER_US = 0.0343f;

volatile uint16_t lastLidarCm = 0;
volatile bool lidarSeen = false;

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
        }
      } else break;
    } else {
      LidarSerial.read();
    }
  }
  return false;
}

uint16_t readUltrasonicCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long dur = pulseIn(ECHO_PIN, HIGH, US_TIMEOUT_US);
  if (dur == 0) return 0;
  float cm = (dur * SOUND_CM_PER_US) * 0.5f;
  if (cm < 0) cm = 0;
  if (cm > 500) cm = 500;
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
  // 버튼: 누르는 동안(LOW) LED ON
  bool btnPressed = (digitalRead(BTN_PIN) == LOW);
  digitalWrite(LED_PIN, btnPressed ? HIGH : LOW);

  // 라이다 최신값 갱신
  uint16_t d, s; float tc;
  if (readTFLuna(d, s, tc)) {
    lastLidarCm = d;
    lidarSeen = true;
  }

  // 1Hz CSV 출력: ultrasonic_cm,lidar_cm,button
  static uint32_t tPrev = 0;
  uint32_t now = millis();
  if (now - tPrev >= 1000) {
    tPrev = now;
    uint16_t us_cm = readUltrasonicCm();
    uint16_t lidar_cm = lidarSeen ? lastLidarCm : 0;
    Serial.printf("%u,%u,%d\n", us_cm, lidar_cm, btnPressed ? 1 : 0);
  }
}
