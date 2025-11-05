#!/usr/bin/env python3
"""
ESP32 초음파 센서 실시간 히트맵 시각화
"""

import json
import signal
import sys
from datetime import datetime
from paho.mqtt import client as mqtt
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.animation import FuncAnimation
import numpy as np

# ========== 설정 ==========
LOCAL_BROKER = "localhost"
LOCAL_PORT = 1883
LOCAL_TOPIC_SUB = "esp/+/+/data"

# A2 용지 크기 (mm)
PAPER_WIDTH = 594
PAPER_HEIGHT = 420

# 원기둥
CYLINDER_DIAMETER = 105

# 센서 위치 (모서리에서 50mm 안쪽)
SENSOR_MARGIN = 50
SENSORS = [
    {'id': 1, 'x': SENSOR_MARGIN, 'y': SENSOR_MARGIN, 'label': 'ESP32-1'},
    {'id': 2, 'x': PAPER_WIDTH - SENSOR_MARGIN, 'y': SENSOR_MARGIN, 'label': 'ESP32-2'},
    {'id': 3, 'x': SENSOR_MARGIN, 'y': PAPER_HEIGHT - SENSOR_MARGIN, 'label': 'ESP32-3'},
    {'id': 4, 'x': PAPER_WIDTH - SENSOR_MARGIN, 'y': PAPER_HEIGHT - SENSOR_MARGIN, 'label': 'ESP32-4'},
]

# 감지 임계값 (cm)
DETECTION_THRESHOLD = 50

# ========== 전역 변수 ==========
ORDER = [f"ESP32-{i}" for i in range(1, 5)]
latest = {k: None for k in ORDER}
client = None
ignore_retained = True

fig, ax = None, None
circles = {}
texts = {}
value_texts = {}


def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _norm_sid(s):
    s = str(s).strip()
    if s.lower().startswith("esp32-"):
        return "ESP32-" + s.split("-", 1)[1]
    return s


def _as_int(v, default=None):
    try:
        if v is None:
            return default
        return int(round(float(v)))
    except Exception:
        return default


def get_sensor_color(value):
    """센서 값에 따른 색상 결정"""
    if value is None:
        return '#94a3b8'  # 회색 - 데이터 없음
    if value < DETECTION_THRESHOLD:
        return '#22c55e'  # 녹색 - 물체 감지
    return '#ef4444'  # 빨강 - 물체 없음


def setup_plot():
    """matplotlib 그래프 초기 설정"""
    global fig, ax, circles, texts, value_texts
    
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.set_xlim(0, PAPER_WIDTH)
    ax.set_ylim(0, PAPER_HEIGHT)
    ax.set_aspect('equal')
    ax.set_xlabel('Width (mm)', fontsize=12)
    ax.set_ylabel('Height (mm)', fontsize=12)
    ax.set_title('ESP32 Ultrasonic Sensor Heatmap - A2 Paper (594×420mm)', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3)
    
    # A2 용지 테두리
    rect = patches.Rectangle((0, 0), PAPER_WIDTH, PAPER_HEIGHT,
                            linewidth=2, edgecolor='black', facecolor='white')
    ax.add_patch(rect)
    
    # 원기둥 참조 (중앙)
    cylinder = plt.Circle((PAPER_WIDTH/2, PAPER_HEIGHT/2), CYLINDER_DIAMETER/2,
                         color='blue', fill=False, linestyle='--', linewidth=2, alpha=0.5)
    ax.add_patch(cylinder)
    ax.text(PAPER_WIDTH/2, PAPER_HEIGHT/2 - CYLINDER_DIAMETER/2 - 20,
           f'원기둥 (Ø{CYLINDER_DIAMETER}mm)', ha='center', fontsize=10, color='blue')
    
    # 센서 위치 및 감지 범위
    for sensor in SENSORS:
        # 감지 범위 원 (초기에는 보이지 않음)
        circle = plt.Circle((sensor['x'], sensor['y']), 0,
                          color='gray', fill=True, alpha=0.1)
        ax.add_patch(circle)
        circles[sensor['label']] = circle
        
        # 센서 위치 점
        ax.plot(sensor['x'], sensor['y'], 'o', markersize=12,
               color='gray', markeredgecolor='white', markeredgewidth=2)
        
        # 센서 번호
        text = ax.text(sensor['x'], sensor['y'] + 20, str(sensor['id']),
                      ha='center', va='bottom', fontsize=12, fontweight='bold')
        texts[sensor['label']] = text
        
        # 센서 값 표시
        value_text = ax.text(sensor['x'], sensor['y'] - 25, '-',
                           ha='center', va='top', fontsize=10, fontweight='bold')
        value_texts[sensor['label']] = value_text
    
    # 범례
    legend_x = PAPER_WIDTH - 100
    legend_y = 50
    ax.plot(legend_x, legend_y, 'o', markersize=10, color='#22c55e', label=f'물체 감지 (<{DETECTION_THRESHOLD}cm)')
    ax.plot(legend_x, legend_y - 20, 'o', markersize=10, color='#ef4444', label=f'물체 없음 (≥{DETECTION_THRESHOLD}cm)')
    ax.plot(legend_x, legend_y - 40, 'o', markersize=10, color='#94a3b8', label='데이터 없음')
    ax.legend(loc='lower right', fontsize=9)
    
    plt.tight_layout()


def update_plot(frame):
    """그래프 업데이트 (애니메이션)"""
    for sensor in SENSORS:
        label = sensor['label']
        value = latest.get(label)
        color = get_sensor_color(value)
        
        # 감지 범위 원 업데이트
        if value is not None:
            radius = value * 10  # cm to mm
            circles[label].set_radius(radius)
            circles[label].set_color(color)
            circles[label].set_alpha(0.1)
            
            # 센서 값 텍스트 업데이트
            value_texts[label].set_text(f'{value} cm')
            value_texts[label].set_color(color)
        else:
            circles[label].set_radius(0)
            value_texts[label].set_text('-')
            value_texts[label].set_color(color)
    
    return list(circles.values()) + list(value_texts.values())


def on_connect(client, userdata, flags, rc):
    print(f"[{get_timestamp()}] 로컬 브로커 연결 성공 (rc={rc})")
    client.subscribe(LOCAL_TOPIC_SUB, qos=1)
    print(f"[{get_timestamp()}] 구독 토픽: {LOCAL_TOPIC_SUB}")
    
    # 게이트웨이 온라인 상태 발행
    gateway_topic = "gateway/301A/status"
    client.publish(gateway_topic, "online", qos=1, retain=True)
    print(f"[{get_timestamp()}] 게이트웨이 온라인 발행: {gateway_topic}")
    print(f"[{get_timestamp()}] ESP32 센서 값 수신 중...\n")


def on_message(client, userdata, msg):
    global ignore_retained
    
    if ignore_retained and msg.retain:
        return
    ignore_retained = False
    
    try:
        data = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"\n[오류] JSON 파싱 실패: {e}")
        return
    
    parts = msg.topic.split("/")
    if len(parts) < 4:
        print(f"\n[오류] 토픽 형식 오류: {msg.topic}")
        return
    
    bed_id = parts[1]
    sensor_id_from_topic = parts[2]
    sensor_id = _norm_sid(data.get("sensor_id") or sensor_id_from_topic)
    
    ultrasonic = _as_int(data.get("ultrasonic"))
    
    if sensor_id in latest and ultrasonic is not None:
        latest[sensor_id] = ultrasonic
        print(f"[{get_timestamp()}] {sensor_id}: {ultrasonic} cm")
    
    # ACK 전송
    ack_topic = f"esp/{bed_id}/{sensor_id_from_topic}/ack"
    status = "received" if ultrasonic is not None else "skipped"
    client.publish(ack_topic, json.dumps({"status": status}), qos=1, retain=False)


def on_disconnect(client, userdata, rc):
    print(f"\n[{get_timestamp()}] 로컬 브로커 연결 해제 (rc={rc})")


def signal_handler(sig, frame):
    print(f"\n\n[{get_timestamp()}] 프로그램 종료 중...")
    if client:
        try:
            gateway_topic = "gateway/301A/status"
            client.publish(gateway_topic, "offline", qos=1, retain=True)
            print(f"[{get_timestamp()}] 게이트웨이 오프라인 발행: {gateway_topic}")
            client.disconnect()
        except Exception:
            pass
    print(f"[{get_timestamp()}] 종료 완료")
    plt.close('all')
    sys.exit(0)


def main():
    global client
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # MQTT 클라이언트 생성
    client = mqtt.Client()
    gateway_topic = "gateway/301A/status"
    client.will_set(gateway_topic, "offline", qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect
    
    print(f"[{get_timestamp()}] ESP32 센서 히트맵 시작...")
    print(f"[{get_timestamp()}] 로컬 브로커: {LOCAL_BROKER}:{LOCAL_PORT}")
    print("=" * 70)
    
    try:
        client.connect(LOCAL_BROKER, LOCAL_PORT, keepalive=60)
        client.loop_start()
        
        # matplotlib 설정 및 애니메이션 시작
        setup_plot()
        ani = FuncAnimation(fig, update_plot, interval=100, blit=True, cache_frame_data=False)
        plt.show()
        
    except ConnectionRefusedError:
        print(f"[{get_timestamp()}] 오류: MQTT 브로커에 연결할 수 없습니다.")
        print(f"[{get_timestamp()}] {LOCAL_BROKER}:{LOCAL_PORT}에서 브로커가 실행 중인지 확인하세요.")
        sys.exit(1)
    except Exception as e:
        print(f"[{get_timestamp()}] 오류: {e}")
        sys.exit(1)
    finally:
        if client:
            client.loop_stop()


if __name__ == "__main__":
    main()