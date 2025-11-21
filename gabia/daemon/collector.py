# /srv/iot/collector.py
import json, os, ssl, logging
import mysql.connector as mc
from paho.mqtt import client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ================== MQTT 설정 ==================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# 라즈베리파이 → 서버 토픽: pi/<NH_ID>/<ROOM_ID>/data
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "pi/+/+/data")

# ================== MySQL 설정 ==================
DB_CFG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "kbu1"),
    password=os.getenv("DB_PASSWORD", "kbu1"),
    database=os.getenv("DB_NAME", "kbuproject_db"),
    autocommit=True,
)

conn = mc.connect(**DB_CFG)
cur = conn.cursor()

# sensor_data 테이블에 맞는 INSERT
# id, timestamp 는 DB에서 자동 생성
SQL_INSERT = """
INSERT INTO sensor_data
    (nursinghome_id, room_id, bed_id, call_button, fall_event)
VALUES
    (%s, %s, %s, %s, %s)
"""


def _as_int(v, default=None):
    try:
        if v is None:
            return default
        return int(round(float(v)))
    except Exception:
        return default


def parse_message(topic: str, payload: bytes):
    """
    토픽: pi/<NH_ID>/<ROOM_ID>/data
    페이로드(JSON):
      {
        "bed_id": "A",
        "call_button": 0 or 1,
        "fall_event": 0 or 1 or 2
      }
    """
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "pi" or parts[3] != "data":
        raise ValueError(f"INVALID_TOPIC: {topic}")

    nursinghome_id = parts[1].strip()
    room_id        = parts[2].strip()

    d = json.loads(payload.decode("utf-8"))

    bed_id = str(d.get("bed_id", "")).strip()
    if not bed_id:
        bed_id = "UNKNOWN"

    # call_button: 0/1로 강제
    call_raw = _as_int(d.get("call_button", 0), 0) or 0
    call_button = 1 if call_raw else 0

    # fall_event: 0/1/2 범위로 클램프
    fe_raw = _as_int(d.get("fall_event", 0), 0)
    if fe_raw is None:
        fall_event = 0
    elif fe_raw < 0:
        fall_event = 0
    elif fe_raw > 2:
        fall_event = 2
    else:
        fall_event = fe_raw

    return (nursinghome_id, room_id, bed_id, call_button, fall_event)


def on_connect(client, userdata, flags, rc):
    logging.info(f"MQTT CONNECTED rc={rc}")
    client.subscribe(MQTT_TOPIC, qos=0)
    logging.info(f"SUBSCRIBE {MQTT_TOPIC}")


def on_message(client, userdata, msg):
    try:
        vals = parse_message(msg.topic, msg.payload)
        cur.execute(SQL_INSERT, vals)
        logging.info(f"INSERT sensor_data OK topic={msg.topic} vals={vals}")
    except Exception:
        logging.exception(f"INSERT sensor_data ERROR topic=%s payload=%r", msg.topic, msg.payload)


def main():
    client = mqtt.Client()
    client.enable_logger()

    # 라즈베리파이와 동일한 TLS 설정
    client.tls_set(
        ca_certs="/etc/mosquitto/certs/ca.crt",
        certfile="/etc/mosquitto/certs/client.crt",
        keyfile="/etc/mosquitto/certs/client.key",
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
