# /srv/iot/collector.py
import json, os, ssl, logging
import mysql.connector as mc
from paho.mqtt import client as mqtt

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# 브로커/토픽
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# 변경: pi/<NH_ID>/<ROOM_ID>/data
TOPIC     = os.getenv("MQTT_TOPIC", "pi/+/+/data")

# DB
DB_CFG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "kbu1"),
    password=os.getenv("DB_PASSWORD", "kbu1"),
    database=os.getenv("DB_NAME", "kbuproject_db"),
    autocommit=True,
)

conn = mc.connect(**DB_CFG)
cur  = conn.cursor()

SQL = (
    "INSERT INTO sensor_data "
    "(nursinghome_id, room_id, bed_id, sensor_id, call_button, fall_event) "
    "VALUES (%s,%s,%s,%s,%s,%s)"
)

def _as_int(v, default=None):
    try:
        return int(v)
    except Exception:
        return default

def parse(topic: str, payload: bytes):
    # topic: pi/<NH_ID>/<ROOM_ID>/data
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "pi" or parts[3] != "data":
        raise ValueError(f"TOPIC_FMT_ERR: {topic}")

    nh_id, room_id = parts[1].strip(), parts[2].strip()

    d = json.loads(payload.decode("utf-8"))
    bed_id     = str(d.get("bed_id", "")).strip()
    sensor_id  = str(d.get("sensor_id", "")).strip()
    call_btn   = 1 if _as_int(d.get("call_button", 0), 0) else 0
    fall_event = 1 if _as_int(d.get("fall_event", 0), 0) else 0

    return (
        nh_id,
        room_id,
        bed_id,
        sensor_id,
        call_btn,
        fall_event,
    )

def on_connect(client, userdata, flags, rc, properties=None):
    logging.info(f"CONNECTED rc={rc}")
    client.subscribe(TOPIC, qos=0)

def on_message(client, userdata, msg):
    try:
        vals = parse(msg.topic, msg.payload)
        cur.execute(SQL, vals)
        logging.info(f"INSERT_OK id={cur.lastrowid} topic={msg.topic} vals={vals}")
    except Exception:
        logging.exception(f"INSERT_ERR topic={msg.topic}")

def main():
    client = mqtt.Client(protocol=mqtt.MQTTv311,
                         callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.enable_logger()
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
