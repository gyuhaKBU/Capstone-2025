# /srv/iot/collector.py
import os, ssl, json, logging
import mysql.connector as mc
from paho.mqtt import client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# MQTT
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "pi/+/+/data")   # 랒파→서버 토픽

# MySQL
DB_CFG = dict(
    host=os.getenv("DB_HOST", "127.0.0.1"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER", "kbu1"),
    password=os.getenv("DB_PASSWORD", "kbu1"),
    database=os.getenv("DB_NAME", "kbuproject_db"),
    autocommit=True,
)

SQL_UPSERT = """
INSERT INTO ultrasonic (sensor_id, ultrasonic)
VALUES (%s, %s)
ON DUPLICATE KEY UPDATE ultrasonic = VALUES(ultrasonic)
"""

conn = cur = None

def ensure_conn():
    global conn, cur
    if conn is None:
        conn = mc.connect(**DB_CFG)
        cur = conn.cursor()
        cur.execute("SET time_zone = '+09:00'")
        return
    try:
        if not conn.is_connected():
            conn.reconnect(attempts=3, delay=2)
            cur = conn.cursor()
            cur.execute("SET time_zone = '+09:00'")
    except Exception:
        conn = mc.connect(**DB_CFG)
        cur = conn.cursor()
        cur.execute("SET time_zone = '+09:00'")

def parse_payload(payload: bytes):
    d = json.loads(payload.decode("utf-8"))
    sensor_id = str(d.get("sensor_id", "")).strip()
    if not sensor_id or len(sensor_id) > 8:
        raise ValueError(f"BAD sensor_id: {sensor_id!r}")
    try:
        ultrasonic = int(d.get("ultrasonic"))
    except Exception:
        raise ValueError(f"BAD ultrasonic: {d.get('ultrasonic')!r}")
    return sensor_id, ultrasonic

def on_connect(client, userdata, flags, rc, properties=None):
    logging.info(f"MQTT CONNECT rc={rc}")
    client.subscribe(MQTT_TOPIC, qos=1)

def on_message(client, userdata, msg):
    try:
        sensor_id, ultrasonic = parse_payload(msg.payload)
        ensure_conn()
        cur.execute(SQL_UPSERT, (sensor_id, ultrasonic))
        logging.info(f"UPSERT_OK topic={msg.topic} sensor_id={sensor_id} ultrasonic={ultrasonic}")
    except Exception as e:
        logging.exception(f"UPSERT_ERR topic={msg.topic}: {e}")

def main():
    ensure_conn()
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
