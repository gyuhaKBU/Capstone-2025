#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* ssid = "inst001-pi0001";
const char* password = "12345678";
const char* mqtt_server = "192.168.4.1";

WiFiClient espClient;
PubSubClient client(espClient);

bool ackReceived = false;

void setup_wifi() {
  delay(10);
  Serial.println("WiFi 연결 중...");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi 연결 완료!");
  Serial.print("IP 주소: ");
  Serial.println(WiFi.localIP());
}

void callback(char* topic, byte* payload, unsigned int length) {
  if (String(topic) == "esp/ack") {
    ackReceived = true;
  }
}

void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT 연결 시도...");
    if (client.connect("ESP8266Client")) {
      Serial.println("연결 성공!");
      client.subscribe("esp/ack");
    } else {
      Serial.print("실패, rc=");
      Serial.println(client.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  setup_wifi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

    if (ackReceived) {
    Serial.print("[응답 수신 완료]");
  } else {
    Serial.println("[경고] 응답 없음, 발행 보류");
    delay(10000);
  }

  int call = random(0, 2);
  int fall = random(0, 2);
  int ultraSonic = random(90, 121);

  StaticJsonDocument<128> doc;
  doc["call"] = call;
  doc["fall"] = fall;
  doc["ultraSonic"] = ultraSonic;

  char buffer[128];
  serializeJson(doc, buffer);

  ackReceived = false;
  client.publish("esp/sensor", buffer);
  Serial.println(String("[발행] ") + buffer);

  unsigned long start = millis();
  while (!ackReceived && millis() - start < 5000) {
    client.loop();
  }



  delay(5000);
}
