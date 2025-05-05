/* ------------------------------------------------- 전처리기 ------------------------------------------------- */
/*  기기 고유 설정  */
#define PATIENT_ID   "p1002" 

#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#define TRIG_PIN D1 // GPIO5 | 초음파 쏴
#define ECHO_PIN D2 // GPIO4 | 초음파 받아
#define BTN_PIN D5  // GPIO14 | 푸시버튼

/* ------------------------------------------------- 전역 변수 ------------------------------------------------- */
/*  와이파이 연결  */
const char *ssid = "inst001-pi0001";
const char *password = "12345678";
const char *mqtt_server = "192.168.4.1";

WiFiClient espClient;
PubSubClient client(espClient);

/*  토픽 문자열 버퍼  */
char topicSensor[32];
char topicAck[32];

/*  갈곳잃은 카테고리  */
bool ackReceived = false;
static unsigned long ackTimer = 0;

/*  멀티태스킹  */
unsigned long previous_button_debounce = 0;
unsigned long previous_readSendSensor = 0;

const unsigned long cycle_button_debounce = 15;   // 디바운싱 샘플 주기 (ms)
const unsigned long cycle_readSendSensor = 5000; // 센서 읽고 전송 주기 (ms)

/*  버튼 디바운스  */
bool lastButtonReading = HIGH; // 풀업 쓸 때 기본 HIGH
bool buttonState = HIGH;
bool btn_pressed = false;
unsigned long lastDebounceTime = 0;

/* ------------------------------------------------- 함수선언 ------------------------------------------------- */
void setup_wifi();
void reconnect();
void callback(char *topic, byte *payload, unsigned int length);
long readUltrasonicDistance();

/* ------------------------------------------------- 셋업함수 ------------------------------------------------- */
void setup()
{
    Serial.begin(115200); // 시리얼

    /*   와이파이 연결  */
    setup_wifi();
    client.setServer(mqtt_server, 1883);
    client.setCallback(callback);

    // + 토픽 생성
    snprintf(topicSensor, sizeof(topicSensor), "esp/%s/sensor", PATIENT_ID);
    snprintf(topicAck,    sizeof(topicAck),    "esp/%s/ack",    PATIENT_ID);

    // + 내 ACK 토픽 구독
    client.subscribe(topicAck);  // ex: "esp/unit01/ack"

    /*   핀 설정  */
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    pinMode(BTN_PIN, INPUT_PULLUP); // 풀업방식 회로 ㄱㄱㄱㄱㄱㄱ
}

/* ------------------------------------------------- 루프함수 ------------------------------------------------- */
void loop()
{
    unsigned long currentMillis = millis();

    if (!client.connected())
    {
        reconnect();
        ackReceived = true;
    }
    client.loop();

    /*  버튼 디바운싱  */
    if (currentMillis - previous_button_debounce >= cycle_button_debounce)
    {
        previous_button_debounce = currentMillis;

        bool reading = digitalRead(BTN_PIN);
        if (reading != lastButtonReading)
        {
            lastDebounceTime = currentMillis; // 상태 변화가 감지된 시점 기록
        }
        lastButtonReading = reading;

        // 읽기 상태가 cycle_button_debounce 이상 유지됐으면 “진짜 변화”로 인정
        if (currentMillis - lastDebounceTime > cycle_button_debounce)
        {
            if (reading != buttonState)
            {
                buttonState = reading;
                if (buttonState == LOW)
                { // 풀업 쓰면 눌렸을 때 LOW
                    btn_pressed = true;
                }
            }
        }
    }

    if (currentMillis - previous_readSendSensor >= cycle_readSendSensor)
    {
        previous_readSendSensor = currentMillis;
        if (ackReceived)
        {

            int call = 0;
            int fall = random(0, 2);
            long ultraSonic = 0;

            /* -------------- 센서 측정 -------------- */
            /*  초음파 센서 측정  */
            ultraSonic = readUltrasonicDistance();

            /*  버튼 호출 처리  */
            if (btn_pressed)
            {
                call = 1;
                btn_pressed = false;
            }
            else
            {
                call = 0;
            }

            /* 센서값 전송 */
            StaticJsonDocument<128> doc;
            doc["call"] = call;
            doc["fall"] = fall;
            doc["ultraSonic"] = ultraSonic;

            char buffer[128];
            serializeJson(doc, buffer);

            // + topicSensor로 publish
            bool ok = client.publish(topicSensor, buffer);
            if (ok) {
                ackReceived = false;
                ackTimer     = currentMillis;
                Serial.print(F("[발행] "));
                Serial.println(buffer);
            } else {
                Serial.println(F("Publish failed"));
            }
        }
        else
        {
            Serial.println("[경고] 응답 없음, 발행 보류");
        }
    }
    // 매 사이클마다
    if (!ackReceived && ackTimer > 0 && currentMillis - ackTimer > 5000)
    {
        ackTimer = 0; // 타이머 초기화
    }
}

/* ------------------------------------------------- 함수 ------------------------------------------------- */
void setup_wifi()
{ // 와이파이 연결
    delay(10);
    Serial.println("WiFi 연결 중...");
    WiFi.begin(ssid, password);
    while (WiFi.status() != WL_CONNECTED)
    {
        delay(200);
        Serial.print(".");
    }
    Serial.println("\nWiFi 연결 완료!");
    Serial.print("IP 주소: ");
    Serial.println(WiFi.localIP());
}
void reconnect()
{
    while (!client.connected()) {
        Serial.print("MQTT 연결 시도...");
        if (client.connect("ESP8266Client")) {
          Serial.println("연결 성공!");
          // ↓ hard-coded "esp/ack" 대신 내 ACK 토픽을 구독
          client.subscribe(topicAck);
        } else {
            Serial.print("실패, rc=");
            Serial.println(client.state());
            delay(2000);
        }
    }
}

void callback(char *topic, byte *payload, unsigned int length)
{ // 랒파 MQTT 구독? 암튼 잘 수신하는지 확인
    // + 내 ACK 토픽과 일치할 때만
    if (strcmp(topic, topicAck) == 0) {
        ackReceived = true;
    }
}

long readUltrasonicDistance()
{ // 초음파 센서값 불러오기
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 타임아웃 30ms (~5m)
    if (duration == 0)
        return -1;
    return duration * 0.034 / 2;
}