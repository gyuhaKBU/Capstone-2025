// ESP32 WROOM32 + TF-Luna(UART) + DHT22
// TF-Luna: +5V, GND, RXD->GPIO17(TX2), TXD->GPIO16(RX2)
// DHT22  : VCC 3.3V, GND, DATA->GPIO27 (10kΩ 풀업 권장)

#include <HardwareSerial.h>
#include <DHT.h>

#define DHTPIN   27
#define DHTTYPE  DHT22

HardwareSerial TF(2);   // UART2
DHT dht(DHTPIN, DHTTYPE);

uint16_t tf_dist = 0;       // cm
uint16_t tf_strength = 0;
float    tf_tempC = NAN;    // 일부 펌웨어만 제공

// TF-Luna 9바이트 프레임 파서. 유효 데이터 얻으면 true
bool readTFLunaFrame(uint16_t &dist, uint16_t &strength, float &tempC) {
  while (TF.available() >= 9) {
    if (TF.peek() != 0x59) { TF.read(); continue; }
    TF.read();                    // 0x59
    if (TF.peek() != 0x59) {      // 두 번째 헤더 확인
      continue;
    }
    TF.read();                    // 0x59

    uint8_t buf[7];
    TF.readBytes(buf, 7);         // D_L D_H S_L S_H T_L T_H CHK
    uint8_t sum = 0x59 + 0x59;
    for (int i=0;i<6;i++) sum += buf[i];
    if (sum != buf[6]) continue;  // 체크섬 실패시 다음 프레임 대기

    dist     = (uint16_t)buf[0] | ((uint16_t)buf[1] << 8);
    strength = (uint16_t)buf[2] | ((uint16_t)buf[3] << 8);
    uint16_t traw = (uint16_t)buf[4] | ((uint16_t)buf[5] << 8);
    // 온도 해석: 모델/펌웨어별 상이. 보편식(참고용): (t/8 - 256)
    tempC = (float)traw / 8.0f - 256.0f;
    return true;
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  TF.begin(115200, SERIAL_8N1, 16, 17);  // RX=16, TX=17
  dht.begin();
}

void loop() {
  // TF-Luna 수신 갱신
  if (readTFLunaFrame(tf_dist, tf_strength, tf_tempC)) {
    // 최신값 갱신됨
  }

  static uint32_t t0 = 0;
  if (millis() - t0 >= 1000) {
    t0 = millis();

    float h = dht.readHumidity();
    float t = dht.readTemperature(); // °C

    // DHT 실패 시 NaN 처리
    bool dht_ok = !(isnan(h) || isnan(t));

    // JSON 라인 출력
    Serial.print(F("{\"dist_cm\":"));
    Serial.print(tf_dist);
    Serial.print(F(",\"strength\":"));
    Serial.print(tf_strength);
    Serial.print(F(",\"tf_tempC\":"));
    if (isnan(tf_tempC)) Serial.print(F("null")); else Serial.print(tf_tempC, 2);
    Serial.print(F(",\"dht_tempC\":"));
    if (dht_ok) Serial.print(t, 2); else Serial.print(F("null"));
    Serial.print(F(",\"dht_humid\":"));
    if (dht_ok) Serial.print(h, 1); else Serial.print(F("null"));
    Serial.println(F("}"));
  }
}
