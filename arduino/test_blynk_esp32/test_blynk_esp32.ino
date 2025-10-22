/***************** Blynk + Button(IRQ) + DHT22 *****************/
#define BLYNK_TEMPLATE_ID   "TMPL6qLXR06uu"
#define BLYNK_TEMPLATE_NAME "Quickstart Template"
#define BLYNK_AUTH_TOKEN    "M4Sy5O1apDZ-nAM-sdzrMFWie_ukmvuq"
#define BLYNK_PRINT Serial

#include <WiFi.h>
#include <WiFiClient.h>
#include <BlynkSimpleEsp32.h>
#include <DHT.h>

/* --- 핀 정의 --- */
#define LED_PIN 2            // 보드 LED(대부분 GPIO2)
#define BTN_PIN 25           // 버튼(버튼-핀 ↔ GND)
#define DHTPIN  27
#define DHTTYPE DHT11

/* --- 버튼 로직 상태 --- */
volatile bool btn_pressed = false;
volatile unsigned long lastDebounce = 0;
const unsigned long DEBOUNCE_MS = 50;
bool btn_sent = false;
unsigned long btn_send_ts = 0;

/* --- WiFi --- */
char ssid[] = "i2151601";
char pass[] = "10910000";

/* --- Blynk --- */
BlynkTimer timer;
DHT dht(DHTPIN, DHTTYPE);

/* V0에서 들어온 값을 V1로 에코 */
BLYNK_WRITE(V0){
  int value = param.asInt();
  Blynk.virtualWrite(V1, value);
}

/* 연결 시 자산 설정 */
BLYNK_CONNECTED(){
  Blynk.setProperty(V3, "offImageUrl", "https://static-image.nyc3.cdn.digitaloceanspaces.com/general/fte/congratulations.png");
  Blynk.setProperty(V3, "onImageUrl",  "https://static-image.nyc3.cdn.digitaloceanspaces.com/general/fte/congratulations_pressed.png");
  Blynk.setProperty(V3, "url", "https://docs/blynk");
}

/* 업타임 전송 */
void sendUptime(){ Blynk.virtualWrite(V2, millis()/1000); }

/* DHT 전송(2.5s) */
void sendDHT(){
  float t = dht.readTemperature();
  float h = dht.readHumidity();
  if (!isnan(t)) Blynk.virtualWrite(V4, t);
  if (!isnan(h)) Blynk.virtualWrite(V5, h);
}

/* 버튼 ISR */
void IRAM_ATTR onButtonPressed(){
  unsigned long now = millis();
  if (now - lastDebounce > DEBOUNCE_MS){
    btn_pressed = true;
    lastDebounce = now;
  }
}

/* 버튼 상태 처리 + LED 1초 ON + V6 펄스 */
void handleButton(){
  unsigned long now = millis();

  if (btn_pressed){
    btn_pressed = false;
    Blynk.virtualWrite(V6, 1);
    btn_sent = true; btn_send_ts = now;
    Serial.println("[BTN] pressed");
  }
  if (btn_sent && now - btn_send_ts >= 200){
    Blynk.virtualWrite(V6, 0);
    btn_sent = false;
  }
}

void setup(){
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(BTN_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(BTN_PIN), onButtonPressed, FALLING);

  dht.begin();

  Blynk.begin(BLYNK_AUTH_TOKEN, ssid, pass);
  // 주기 작업
  timer.setInterval(1000L, sendUptime);
  timer.setInterval(2500L, sendDHT);
}

void loop(){
  Blynk.run();
  timer.run();
  handleButton();
}
