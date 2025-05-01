#define BUTTON_PIN D5  // GPIO14

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT); // 풀업 X, 풀다운이니까 INPUT
}

void loop() {
  if (digitalRead(BUTTON_PIN) == HIGH) {
    Serial.println("버튼 눌림");
    delay(300);
  }
}
