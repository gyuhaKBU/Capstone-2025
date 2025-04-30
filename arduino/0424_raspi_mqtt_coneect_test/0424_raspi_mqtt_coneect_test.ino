#include <ESP8266WiFi.h>
#include <PubSubClient.h>

const char* ssid = "pi0001";
const char* password = "12345678";
const char* mqtt_server = "192.168.35.119";

WiFiClient espClient;
PubSubClient client(espClient);

void setup_wifi() {
  Serial.print("WiFi 연결 중...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi 연결 완료!");
  Serial.print("IP 주소: ");
  Serial.println(WiFi.localIP());
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT 재연결 중...");
    if (client.connect("espClient001")) {
      Serial.println("MQTT 연결 성공!");
    } else {
      Serial.print("실패. 에러 코드: ");
      Serial.print(client.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000); // 시리얼 안정화 대기
  setup_wifi();

  client.setServer(mqtt_server, 1883);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  client.publish("esp/test", "Hello MQTT");
  delay(5000);
}
