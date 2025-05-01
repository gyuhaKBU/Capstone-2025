/* ------------------------------------------------- 전처리기 ------------------------------------------------- */

#define TRIG_PIN D1  // GPIO5
#define ECHO_PIN D2  // GPIO4
#define btn D5       // 몰라


/* ------------------------------------------------- 변수 ------------------------------------------------- */

//멀티태스킹 변수 개의 독립적인 작업을 millis() 기반으로 처리

//사이클마다의 변수에 현재시간 갱신
unsigned long previous_button_debounce = 0;
unsigned long previous_ultraSonic = 0;
unsigned long previous_button = 0;

//사이클
const unsigned long cycle_button_debounce = 50;
const unsigned long cycle_ultraSonic = 1000;
const unsigned long cycle_button = 2000;

bool lastBtnState = LOW;
bool btn_pressed = false; //버튼 누름 여부

bool reading = LOW;



/* ------------------------------------------------- 함수선언언 ------------------------------------------------- */

long readUltrasonicDistance(); //초음파센서 읽는 함수 선언


/* ------------------------------------------------- 셋업함수 ------------------------------------------------- */

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(btn, INPUT);
}


/* ------------------------------------------------- 루프함수 ------------------------------------------------- */

void loop() {
  unsigned long currentMillis = millis(); //루프마다 현재시간 갱신

  reading = digitalRead(btn);

  // 버튼을 눌렀다가 뗐을 때 (전이 감지)
  if (reading == HIGH && lastBtnState == LOW) {
    Serial.println("호출");
    delay(300); // 중복 감지 방지
  }

  lastBtnState = reading;
  
  

  if (currentMillis - previous_ultraSonic >= cycle_ultraSonic){ //초음파센서 사이클
    previous_ultraSonic = currentMillis;

    long distance = readUltrasonicDistance(); //초음파센서 불러오기 및 출력
    Serial.print("거리: ");
    Serial.print(distance);
    Serial.println(" cm | ");
  }

  if (currentMillis - previous_button >= cycle_button){ //호출여부 사이클
    previous_button = currentMillis;

    if(btn_pressed){ //현재 사이클 한 번 돌기 전 버튼 한 번 이상 눌렀으면
      Serial.println("호출");
      btn_pressed = false; //다시 변수 false로
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

  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms 제한 (~5m)
  if (duration == 0) return -1; // timeout 처리
  long distanceCm = duration * 0.034 / 2;

  return distanceCm;
}