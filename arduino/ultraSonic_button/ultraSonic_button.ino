/* ------------------------------------------------- 전처리기 ------------------------------------------------- */
#define TRIG_PIN       D1   // GPIO5
#define ECHO_PIN       D2   // GPIO4
#define BTN_PIN        D5   // 푸시버튼

/* ------------------------------------------------- 변수 ------------------------------------------------- */
/*  멀티태스킹킹  */
unsigned long previous_button_debounce = 0;
unsigned long previous_ultraSonic      = 0;
unsigned long previous_button          = 0;

const unsigned long cycle_button_debounce = 10;    // 디바운싱 샘플 주기 (ms)
const unsigned long cycle_ultraSonic      = 1000;  // 초음파 센서 주기 (ms)
const unsigned long cycle_button          = 2000;  // “호출” 출력 주기 (ms)

/*  버튼 디바운스  */
bool lastButtonReading = HIGH;  // 풀업 쓸 때 기본 HIGH
bool buttonState       = HIGH;
bool btn_pressed       = false;
unsigned long lastDebounceTime = 0;

/* ------------------------------------------------- 함수선언 ------------------------------------------------- */
long readUltrasonicDistance();

/* ------------------------------------------------- 셋업함수 ------------------------------------------------- */
void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(BTN_PIN, INPUT_PULLUP);   // 내부 풀업 사용
}

/* ------------------------------------------------- 루프함수 ------------------------------------------------- */
void loop() {
  unsigned long currentMillis = millis();

  // 1) 디바운싱 샘플링
  if (currentMillis - previous_button_debounce >= cycle_button_debounce) {
    previous_button_debounce = currentMillis;
    
    bool reading = digitalRead(BTN_PIN);
    if (reading != lastButtonReading) {
      lastDebounceTime = currentMillis;  // 상태 변화가 감지된 시점 기록
    }
    lastButtonReading = reading;

    // 읽기 상태가 cycle_button_debounce 이상 유지됐으면 “진짜 변화”로 인정
    if (currentMillis - lastDebounceTime > cycle_button_debounce) {
      if (reading != buttonState) {
        buttonState = reading;
        if (buttonState == LOW) {       // 풀업 쓰면 눌렸을 때 LOW
          btn_pressed = true;
        }
      }
    }
  }

  // 2) 초음파 센서 측정 (1초마다)
  if (currentMillis - previous_ultraSonic >= cycle_ultraSonic) {
    previous_ultraSonic = currentMillis;

    long distance = readUltrasonicDistance();
    Serial.print("거리: ");
    if (distance < 0) Serial.println("Out of range");
    else {
      Serial.print(distance);
      Serial.println(" cm");
    }
  }

  // 3) 버튼 호출 처리 (2초마다 한 번)
  if (currentMillis - previous_button >= cycle_button) {
    previous_button = currentMillis;
    if (btn_pressed) {
      Serial.println("호출");
      btn_pressed = false;
    }
  }
}

/* ------------------------------------------------- 함수 ------------------------------------------------- */
long readUltrasonicDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 타임아웃 30ms (~5m)
  if (duration == 0) return -1;
  return duration * 0.034 / 2;
}
