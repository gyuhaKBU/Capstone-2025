#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* ssid = "inst001-pi0001";            // 라즈베리파이 핫스팟 SSID
const char* password = "12345678";      // 핫스팟 비밀번호
const char* mqtt_server = "192.168.137.2"; // 라즈베리파이 IP 주소 (eth0 기준)

WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
  delay(10);
  Serial.println("WiFi 연결 중...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("WiFi 연결 완료!");
  Serial.print("IP 주소: ");
  Serial.println(WiFi.localIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT 연결 시도...");
    if (client.connect("ESP8266Client")) {
      Serial.println("연결 성공!");
    } else {
      Serial.print("실패, rc=");
      Serial.print(client.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();
  client.setServer(mqtt_server, 1883); // 라즈베리파이 MQTT 포트
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // 랜덤 값 생성
  int call = random(0, 2); // 0 or 1
  int fall = random(0, 2);
  int ultraSonic = random(90, 121);

  // JSON 구성
  StaticJsonDocument<128> doc;
  doc["call"] = call;
  doc["fall"] = fall;
  doc["ultraSonic"] = ultraSonic;

  char buffer[128];
  serializeJson(doc, buffer);

  // 메시지 발행
  client.publish("esp/sensor", buffer);
  Serial.println(buffer);

  delay(5000); // 5초 간격
}
