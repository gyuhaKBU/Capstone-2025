# data_logger.py
import serial
import time

# --- 설정 (아래 두 값을 반드시 확인하고 필요시 수정하세요) ---

# 1. 아두이노가 연결된 USB 포트 이름
# 터미널에 'ls /dev/tty*'를 입력하여 '/dev/ttyACM0' 또는 '/dev/ttyUSB0' 등으로 확인 후 수정
SERIAL_PORT = '/dev/ttyUSB0'

# 2. 생성될 로그 파일 이름
LOG_FILE = 'sensor_log.txt' 

# --- 프로그램 설정 (수정 필요 없음) ---
READ_INTERVAL = 0.1 # 0.1초 간격으로 데이터 읽기

# --- 메인 프로그램 ---
print(f"'{SERIAL_PORT}' 포트에서 데이터 로깅을 시작합니다.")
print(f"데이터는 '{LOG_FILE}' 파일에 저장됩니다.")
print("다양한 상황(걷기, 앉기, 낙상 흉내)을 테스트해주세요.")
print("로깅을 중지하려면 키보드에서 Ctrl+C를 누르세요.")

try:
    # 지정된 시리얼 포트와 통신 속도로 연결을 시도합니다.
    ser = serial.Serial(SERIAL_PORT, 115200, timeout=1)
    
    # 'with' 구문을 사용하면 프로그램이 종료될 때 파일이 자동으로 안전하게 닫힙니다.
    with open(LOG_FILE, 'w') as f:
        while True:
            # 시리얼 버퍼에 데이터가 있는지 확인합니다.
            if ser.in_waiting > 0:
                # 아두이노로부터 "210,208,0"과 같은 한 줄의 데이터를 읽습니다.
                line = ser.readline().decode('utf-8').rstrip()
                
                # 읽은 데이터를 화면에 출력합니다.
                print(line)
                
                # 읽은 데이터를 파일에 한 줄씩 기록합니다.
                f.write(line + '\n')
                
            # 0.1초 동안 잠시 대기합니다.
            time.sleep(READ_INTERVAL)
            
except KeyboardInterrupt:
    # 사용자가 Ctrl+C를 누르면 로깅을 정상적으로 중지합니다.
    print(f"\n로깅 중지. 데이터가 '{LOG_FILE}'에 성공적으로 저장되었습니다.")
except serial.serialutil.SerialException:
    print(f"\n에러: '{SERIAL_PORT}' 포트를 찾을 수 없거나 접근 권한이 없습니다.")
    print("1. 아두이노가 라즈베리파이에 제대로 연결되었는지 확인하세요.")
    print("2. 'ls /dev/tty*' 명령어로 정확한 포트 이름을 확인하고 코드를 수정하세요.")
except Exception as e:
    # 그 외 예기치 못한 에러가 발생했을 때 메시지를 출력합니다.
    print(f"\n에러가 발생했습니다: {e}")