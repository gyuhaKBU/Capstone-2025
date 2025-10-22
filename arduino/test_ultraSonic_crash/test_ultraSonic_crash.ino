// ESP32S + HC-SR04: TRIG=27, ECHO=33
#define TRIG_PIN 27
#define ECHO_PIN 33

const unsigned long PERIOD_MS = 500;
const unsigned long US_TIMEOUT = 30000; // ~5 m
size_t prev_len = 0;
unsigned long t0 = 0;

uint16_t readUltrasonicCm() {
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long us = pulseIn(ECHO_PIN, HIGH, US_TIMEOUT);
  if (us == 0) return 0;
  float cm = (us * 0.0343f) * 0.5f;
  if (cm < 0) cm = 0;
  if (cm > 500) cm = 500;
  return (uint16_t)(cm + 0.5f);
}

void printOverwrite(const char* s) {
  Serial.println(s);              // 새 값 출력
  // 이전 글자 수가 더 길면 남은 부분 지우기
  size_t len = strlen(s);
  if (prev_len > len) {
    for (size_t i = 0; i < prev_len - len; ++i)
    Serial.println(s);
  }
  prev_len = len;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
}

void loop() {
  if (millis() - t0 >= PERIOD_MS) {
    t0 = millis();
    uint16_t cm = readUltrasonicCm();
    char buf[8];
    snprintf(buf, sizeof(buf), "%u", cm); // 정수만
    printOverwrite(buf);                  // 같은 줄 덮어쓰기
  }
}