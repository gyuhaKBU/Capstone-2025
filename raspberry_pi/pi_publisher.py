#!/usr/bin/env python3
import os, json, ssl, time, signal, sys, csv, joblib
from datetime import datetime
from collections import defaultdict, deque
import numpy as np
import pandas as pd
from paho.mqtt import client as mqtt

# ========= 기본 설정 =========
NURSINGHOME_ID = "NH-001"
ROOM_ID        = "301A"

SERVER_HOST = "121.78.128.175"
MQTT_PORT   = 8883

# 서버로 올리는 주제
TOPIC               = f"pi/{NURSINGHOME_ID}/{ROOM_ID}/data"   # 예: pi/NH-001/301A/data
# ESP → 라즈베리파이 수신 주제
LOCAL_TOPIC_SUB     = "esp/+/+/data"                          # esp/{bed_id}/{sensor_id}/data
# 게이트웨이 상태 주제
GATEWAY_STATUS_TOPIC = f"gateway/{ROOM_ID}/status"            # 예: gateway/301A/status

LOCAL_BROKER        = "localhost"
LOCAL_PORT          = 1883

CA_FILE   = "/home/capstone/Desktop/certs/ca.crt"
CERT_FILE = "/home/capstone/Desktop/certs/client.crt"
KEY_FILE  = "/home/capstone/Desktop/certs/client.key"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# bed_id별로 최근 8개 시계열을 쌓을 버퍼
# blocks[bed_id] = deque(maxlen=8)  # 각 원소는 {"timestamp": ..., "ESP32-1": ..., ...}
blocks = defaultdict(lambda: deque(maxlen=8))

# label_out 폴더 생성 (없으면 자동 생성)
LABEL_DIR = os.path.join(SCRIPT_DIR, "label_out")
os.makedirs(LABEL_DIR, exist_ok=True)

# label_out 폴더 안에 저장할 CSV 경로
CSV_PATH = os.path.join(LABEL_DIR, "unlabeled_NH-001_301A.csv")

# 실시간 머신러닝 추론
MODEL_DIR    = "/home/capstone/venvs/iot/model"
XGB_PATH     = os.path.join(MODEL_DIR, "xgb_model.pkl")
SCALER_PATH  = os.path.join(MODEL_DIR, "scaler.pkl")
FEAT_PATH    = os.path.join(MODEL_DIR, "feature_order.json")

xgb_model = joblib.load(XGB_PATH)
scaler    = joblib.load(SCALER_PATH)

with open(FEAT_PATH, "r") as f:
    FEATURE_ORDER = json.load(f)

ULTRA_COLS   = ["ESP32-1", "ESP32-2", "ESP32-3", "ESP32-4"]
CSV_COLUMNS  = ["timestamp", "bed_id"] + ULTRA_COLS
STATS      = ["mean", "std", "min", "max", "median"]

# bed_id별 최신 센서 상태 (CSV/스냅샷용)
bed_ultra_state = defaultdict(lambda: {cid: None for cid in ULTRA_COLS})

ultra_state = {cid: None for cid in ULTRA_COLS}

# 초음파 플러시 주기(초) – 0.2초마다 한 번씩 저장 시도
ULTRA_FLUSH_INTERVAL = 0.2
last_ultra_flush = 0.0  # 마지막으로 CSV 기록 시도한 시각

# bed_id별 시계열 버퍼 (윈도우 용)
WINDOW_SIZE   = 8   # 1.6초
WINDOW_STRIDE = 2   # 0.4초
bed_series    = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
bed_step      = defaultdict(int)  # stride 제어용 카운터

# --- fall_event 상태 계산용 설정 ---
PRED_INTERVAL_SEC = ULTRA_FLUSH_INTERVAL * WINDOW_STRIDE  # 0.4s 기준

FALL_WARN_SEC   = 1.0   # 2초 연속 2 → 경고
FALL_WINDOW_SEC = 5.2   # 5초 창
FALL_SUM_SEC    = 0.6   # 5초 안에 총 2초 이상 2 → 위험 후보

FALL_WARN_STEPS   = int(FALL_WARN_SEC   / PRED_INTERVAL_SEC + 0.5)  # ≈ 5
FALL_WINDOW_STEPS = int(FALL_WINDOW_SEC / PRED_INTERVAL_SEC + 0.5)  # ≈ 13
FALL_SUM_STEPS    = int(FALL_SUM_SEC    / PRED_INTERVAL_SEC + 0.5)  # ≈ 5

# bed별 원시 예측 히스토리와 직전 예측
fall_pred_hist = defaultdict(lambda: deque(maxlen=FALL_WINDOW_STEPS))
last_raw_pred  = defaultdict(int)
# ------------------------------------

# 초당 5번(0.2s) 스냅샷 저장을 위한 타이머
ULTRA_FLUSH_INTERVAL = 0.2
last_ultra_flush = 0.0


# 집계 발행 최소 간격(초)
SERVER_PUB_INTERVAL = float(os.getenv("SERVER_PUB_INTERVAL", "1.0"))

def _as_int(v, default=None):
    try:
        if v is None:
            return default
        return int(round(float(v)))
    except Exception:
        return default

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


# ========= 서버 퍼블리셔 =========
server_client = mqtt.Client(protocol=mqtt.MQTTv311)
if MQTT_PORT == 8883:
    server_client.tls_set(
        ca_certs=CA_FILE,
        certfile=CERT_FILE,
        keyfile=KEY_FILE,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
server_client.connect(SERVER_HOST, MQTT_PORT, keepalive=60)
server_client.loop_start()
print(f"[{get_timestamp()}] 서버 연결 완료: {SERVER_HOST}:{MQTT_PORT}")


# ========= 로컬 수집 + 집계 상태 =========
# bed_id별로 버튼/낙상, 마지막 전송 정보만 관리 (ultrasonic은 서버로 안 보냄)
beds = defaultdict(lambda: {
    "call_button": 0,
    "fall_event": 0,
    "last_pub": 0.0,
    "last_sent_sig": None,   # 직전 전송 시그니처(중복 방지)
})


def _build_payload(bed_id: str, bstate: dict):
    payload = {
        "bed_id": bed_id,
        "call_button": int(bstate["call_button"] or 0),
        "fall_event": int(bstate["fall_event"] or 0),
    }
    return payload

def _flush_ultrasonic_if_due():
    global last_ultra_flush

    now = time.time()
    if now - last_ultra_flush < ULTRA_FLUSH_INTERVAL:
        return
    last_ultra_flush = now

    ts = get_timestamp()

    for bed_id, state in bed_ultra_state.items():
        vals = [state[cid] for cid in ULTRA_COLS]
        non_empty = sum(v is not None for v in vals)
        if non_empty < 3:
            continue

        # CSV 기록
        row = [ts, bed_id] + [v if v is not None else "" for v in vals]

        file_exists = os.path.exists(CSV_PATH)
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(CSV_COLUMNS)
            writer.writerow(row)

        # 윈도우용 버퍼에 추가
        bed_series[bed_id].append({
            "timestamp": ts,
            "ESP32-1": vals[0],
            "ESP32-2": vals[1],
            "ESP32-3": vals[2],
            "ESP32-4": vals[3],
        })
        bed_step[bed_id] += 1

        # 여기서 바로 모델 실행
        _maybe_run_model_for_bed(bed_id)


def extract_features_from_window(window_rows):
    """
    window_rows: 길이 8 리스트, 각 원소는 {"timestamp":..., "ESP32-1":..., ...}
    반환: (20,) numpy 배열. 품질 나쁘면 None.
    """
    feats = {}

    for col in ULTRA_COLS:
        arr = np.array([row[col] for row in window_rows], dtype=float)

        # 실시간에서는 라벨 기반 보간 못 하므로, 
        # 음수/NaN 있으면 이 윈도우는 버리는 방식이 가장 단순하다.
        if np.any((arr < 0) | np.isnan(arr)):
            return None

        feats[f"{col}_mean"]   = float(arr.mean())
        feats[f"{col}_std"]    = float(arr.std())
        feats[f"{col}_min"]    = float(arr.min())
        feats[f"{col}_max"]    = float(arr.max())
        feats[f"{col}_median"] = float(np.median(arr))

    # FEATURE_ORDER 순서에 맞춰 벡터 구성
    x_vec = np.array([feats[k] for k in FEATURE_ORDER], dtype=float)
    return x_vec

    
def _maybe_run_model_for_bed(bed_id: str):
    buf = bed_series[bed_id]
    if len(buf) < WINDOW_SIZE:
        return

    # stride=2 → 샘플 두 개마다 한 번만 예측
    if bed_step[bed_id] % WINDOW_STRIDE != 0:
        return

    window_rows = list(buf)  # 최근 8개
    x_raw = extract_features_from_window(window_rows)
    if x_raw is None:
        return

    # FEATURE_ORDER 순서에 맞게 컬럼 이름 붙여서 DataFrame 생성
    x_df = pd.DataFrame([x_raw], columns=FEATURE_ORDER)

    # 스케일링 (이제 경고 안 뜸)
    x_scaled = scaler.transform(x_df)

    # 예측 (라벨 0/1/2)
    proba = xgb_model.predict_proba(x_scaled)[0]
    y_hat = int(np.argmax(proba))   # 원시 예측값
    conf  = float(proba[y_hat])

    ts = get_timestamp()

    # -----------------------------
    # fall_event 상태머신 업데이트
    # -----------------------------
    hist = fall_pred_hist[bed_id]
    prev_raw = last_raw_pred[bed_id]

    hist.append(y_hat)
    last_raw_pred[bed_id] = y_hat

    # hist 안에서 연속된 2(run length) 계산
    run_2 = 0
    for v in reversed(hist):
        if v == 2:
            run_2 += 1
        else:
            break

    # 5초 창 안에서 2의 개수 (≈ 2초 이상인지 판단용)
    cnt_2 = sum(1 for v in hist if v == 2)

    bstate = beds[bed_id]
    cur_state = int(bstate.get("fall_event", 0))

    new_state = cur_state

    # 3) 5초 안에 2의 총합이 2초 이상 이다가 0이 되면 → 2(위험)
    #    조건: 직전 원시 예측이 2, 현재 0, 그리고 창 안의 2 개수가 FALL_SUM_STEPS 이상
    if prev_raw == 2 and y_hat == 0 and cnt_2 >= FALL_SUM_STEPS:
        new_state = 2

    # 2) 2가 2초 이상(연속) 지속되면 → 1(경고)
    elif run_2 >= FALL_WARN_STEPS:
        new_state = 1

    # 1) fall_event값을 0/1만 유지하면 → 0(안정)
    #    구현: 최근 5초 창 안에 2가 하나도 없으면 안정으로 리셋
    elif cnt_2 == 0:
        new_state = 0

    # 그 외(2가 조금 섞였지만 기준 미달)는 기존 상태 유지

    bstate["fall_event"] = new_state

    # 터미널에 원시 예측 + 최종 상태 같이 출력
    proba_rounded = np.round(proba, 3)
    print(f"모델왈={y_hat} 상태={new_state} conf={conf:.3f} proba={proba_rounded} hist={list(hist)}")

    # 여기서는 fall_event를 beds에만 저장하고,
    # 서버 전송은 아직 하지 않으므로 _maybe_publish를 부르지 않는다.
    # (_maybe_publish 호출은 아래 on_local_message 쪽에서 call_button용으로만 유지)

def _sig_of(bed_id: str, bstate: dict):
    return (
        bed_id,
        int(bstate["call_button"] or 0),
        int(bstate["fall_event"] or 0),
    )


def _maybe_publish(bed_id: str, prev_call: int | None = None):
    bstate = beds[bed_id]
    now = time.time()

    # 최소 전송 간격
    if now - bstate["last_pub"] < SERVER_PUB_INTERVAL:
        return

    cur_call = int(bstate["call_button"] or 0)
    cur_fall = int(bstate["fall_event"] or 0)

    last_sig = bstate["last_sent_sig"]
    send = False

    if last_sig is None:
        # 프로그램 시작 후 첫 전송
        send = True
    else:
        _, last_call, last_fall = last_sig

        # 1) fall_event 값이 바뀌면 전송
        if cur_fall != last_fall:
            send = True

        # 2) call_button이 0 -> 1로 바뀐 경우에만 전송
        if prev_call is not None and prev_call == 0 and cur_call == 1:
            send = True

    if not send:
        return

    payload = {
        "bed_id": bed_id,
        "call_button": cur_call,   # 현재 상태 그대로 실어 보냄
        "fall_event": cur_fall,
    }

    res = server_client.publish(TOPIC, json.dumps(payload), qos=0, retain=False)
    if res.rc == mqtt.MQTT_ERR_SUCCESS:
        bstate["last_pub"] = now
        bstate["last_sent_sig"] = (bed_id, cur_call, cur_fall)
    else:
        print(f"\n[{get_timestamp()}] 서버 전송 실패 rc={res.rc}")


# ========= 로컬 브로커(ESP → PI) 콜백 =========
ignore_retained = True
local_client = None


def on_local_connect(client, userdata, flags, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 성공 (rc={rc})")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)
    print(f"[{get_timestamp()}] 구독 토픽: {LOCAL_TOPIC_SUB}")
    # 온라인 상태 발행
    client.publish(GATEWAY_STATUS_TOPIC, "online", qos=1, retain=True)
    print(f"[{get_timestamp()}] [상태] 게이트웨이 online 발행: {GATEWAY_STATUS_TOPIC}")


def on_local_message(client, userdata, msg):
    global ignore_retained

    if ignore_retained and msg.retain:
        return
    ignore_retained = False

    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"\n[오류] JSON 파싱 실패: {e}")
        return

    parts = msg.topic.split("/")  # esp/{bed_id}/{sensor_id}/data
    if len(parts) < 4:
        print(f"\n[오류] 토픽 형식 오류: {msg.topic}")
        return

    bed_id = parts[1]
    sensor_id_from_topic = parts[2]

    # 여기서는 ultrasonic은 모델용/CSV용으로만 사용
    u_val = data.get("ultrasonic_cm", data.get("ultrasonic"))

    call_raw = _as_int(data.get("call_button"), 0) or 0
    call_button = 1 if call_raw else 0

    bstate = beds[bed_id]
    prev_call = int(bstate["call_button"] or 0)
    bstate["call_button"] = call_button

    # ----- 초음파 값 bed별 상태에 반영 -----
    # 토픽에서 센서 ID 정규화 (예: esp32-1 → ESP32-1)
    sensor_id = sensor_id_from_topic
    if sensor_id.lower().startswith("esp32-"):
        sensor_id = "ESP32-" + sensor_id.split("-", 1)[1]

    if u_val is not None and sensor_id in ULTRA_COLS:
        try:
            bed_ultra_state[bed_id][sensor_id] = float(u_val)
        except Exception:
            pass
    # --------------------------------------

    # ----- ACK 발행 (pi_labeling.py와 동일 패턴) -----
    status = "received" if u_val is not None else "skipped"
    ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
    client.publish(ack_topic, json.dumps({"status": status}), qos=1, retain=False)
    # ---------------------------------------------

    # 초음파 버퍼/모델 실행
    _flush_ultrasonic_if_due()

    # 서버 전송 조건:
    # - call_button: 0 -> 1 이면 전송
    # - fall_event: 마지막으로 보낸 값에서 바뀌면 전송
    _maybe_publish(bed_id, prev_call)


def on_local_disconnect(client, userdata, rc):
    print(f"\n[{get_timestamp()}] 로컬 브로커 연결 해제 (rc={rc})")


def signal_handler(sig, frame):
    ts = get_timestamp()
    print(f"\n[{ts}] 프로그램 종료 중...")
    if local_client:
        try:
            local_client.publish(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)
            print(f"[{ts}] [상태] 게이트웨이 offline 발행: {GATEWAY_STATUS_TOPIC}")
            local_client.disconnect()
        except Exception:
            pass
    if server_client:
        try:
            server_client.loop_stop()
            server_client.disconnect()
        except Exception:
            pass
    print(f"[{ts}] 종료 완료")
    sys.exit(0)


# ========= 메인 =========
def main():
    global local_client

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    local_client = mqtt.Client()
    # LWT: 비정상 종료 시 offline 자동 발행
    local_client.will_set(GATEWAY_STATUS_TOPIC, "offline", qos=1, retain=True)

    local_client.on_connect    = on_local_connect
    local_client.on_message    = on_local_message
    local_client.on_disconnect = on_local_disconnect

    local_client.connect(LOCAL_BROKER, LOCAL_PORT, keepalive=60)

    print(f"[{get_timestamp()}] 게이트웨이 브리지 시작...")
    print(f"  요양원 ID: {NURSINGHOME_ID}")
    print(f"  방 ID: {ROOM_ID}")
    print(f"  서버: {SERVER_HOST}:{MQTT_PORT}")
    print(f"  로컬 브로커: {LOCAL_BROKER}:{LOCAL_PORT}")
    print("=" * 60)

    local_client.loop_forever()


if __name__ == "__main__":
    main()
