# /srv/iot/collector.py
import json, os, ssl, logging, math
import mysql.connector as mc
from paho.mqtt import client as mqtt

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# MQTT
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# 형식: pi/<NH_ID>/<ROOM_ID>/data
TOPIC     = os.getenv("MQTT_TOPIC", "pi/+/+/data")

# MySQL
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
    "INSERT INTO ultrasonic_u4 "
    "(nursinghome_id, room_id, bed_id, call_button, fall_event, u1, u2, u3, u4, lidar) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)

def _as_int(v, default=None):
    try:
        if v is None: return default
        # "12.7" 같은 값도 반올림
        return int(round(float(v)))
    except Exception:
        return default

def _first_int(d, *keys, default=None):
    for k in keys:
        if k in d:
            return _as_int(d.get(k), default)
    return default

def parse(topic: str, payload: bytes):
    # topic: pi/<NH_ID>/<ROOM_ID>/data
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "pi" or parts[3] != "data":
        raise ValueError(f"TOPIC_FMT_ERR: {topic}")
    nh_id, room_id = parts[1].strip(), parts[2].strip()

    d = json.loads(payload.decode("utf-8"))

    bed_id     = str(d.get("bed_id", "")).strip()
    call_btn   = 1 if _as_int(d.get("call_button", 0), 0) else 0
    fall_event = 1 if _as_int(d.get("fall_event", 0), 0) else 0

    # 거리값 수집 우선순위:
    # 1) 명시적 u1~u4
    # 2) 배열 u = [..]
    # 3) 단일 ultrasonic -> u1로 저장
    u1 = _first_int(d, "u1")
    u2 = _first_int(d, "u2")
    u3 = _first_int(d, "u3")
    u4 = _first_int(d, "u4")

    if any(v is not None for v in (u1,u2,u3,u4)) is False and isinstance(d.get("u"), list):
        arr = d["u"]
        u1 = _as_int(arr[0]) if len(arr) > 0 else None
        u2 = _as_int(arr[1]) if len(arr) > 1 else None
        u3 = _as_int(arr[2]) if len(arr) > 2 else None
        u4 = _as_int(arr[3]) if len(arr) > 3 else None

    if all(v is None for v in (u1,u2,u3,u4)) and "ultrasonic" in d:
        u1 = _as_int(d.get("ultrasonic"))

    lidar = _first_int(d, "lidar", "tfmini", "tfluna")

    return (nh_id, room_id, bed_id, call_btn, fall_event, u1, u2, u3, u4, lidar)

def on_connect(client, userdata, flags, rc, properties=None):
    logging.info(f"CONNECTED rc={rc}")
    client.subscribe(TOPIC, qos=0)

def on_message(client, userdata, msg):
    try:
        vals = parse(msg.topic, msg.payload)
        cur.execute(SQL, vals)
        logging.info(f"INSERT_OK id={cur.lastrowid} topic={msg.topic} vals={vals}")
    except Exception:
        logging.exception(f"INSERT_ERR topic={msg.topic} payload={msg.payload!r}")

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
