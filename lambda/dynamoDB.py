import json, os, boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

# ────────────────────────────
# 공통 설정
# ────────────────────────────
dynamodb      = boto3.resource('dynamodb')
table_data    = dynamodb.Table('devicedata')   # ← 기존 테이블
table_user    = dynamodb.Table('User')         # ← 로그인 테이블

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",  # 개발단계 * , 운영 시 도메인 지정
    "Access-Control-Allow-Headers":
        "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Content-Type": "application/json"
}

SIGNUP_PATH      = "/signup"
LOGIN_PATH      = "/login"
DEVICEDATA_PATH = "/devicedata"

# ────────────────────────────
# 헬퍼
# ────────────────────────────
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o % 1 == 0 else float(o)
        return super().default(o)

def resp(code, body):
    return {
        "statusCode": code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }
    
def build_response(status_code: int, body: dict | str):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }
    
# ────────────────────────────
# Lambda 엔트리
# ────────────────────────────
def lambda_handler(event, context):
    # OPTIONS ─── pre-flight 처리
    if event.get("httpMethod") == "OPTIONS":
        return resp(200, {"message": "CORS pre-flight OK"})

    try:
        method = event.get("httpMethod", "")
        path   = event.get("path", "")

        # ────── 로그인  ──────
        if method == "POST" and path == LOGIN_PATH:
            return handle_login(event)

        # ────── 회원가입 ──────
        if method == "POST" and path == SIGNUP_PATH:
            return handle_signup(event)
        
        # ────── devicedata 검색 ──────
        if method == "GET" and path == DEVICEDATA_PATH:
            return handle_devicedata(event)
        

        # 정의되지 않은 조합
        return resp(404, {"message": "Not Found"})

    except Exception as e:
        print("ERROR:", e)
        return resp(500, {"message": f"Internal Error: {e}"})

# ────────────────────────────
# /signup
# ────────────────────────────
def handle_signup(event):
    body = json.loads(event.get("body") or "{}")
    username = body.get("username")
    email    = body.get("email")
    password = body.get("password")
    role     = body.get("role", "staff")

    if not username or not email or not password:
        return resp(400, {"message":"username, email, password는 필수입니다."})

    # 중복 이메일 검사
    if "Item" in table_user.get_item(Key={"email": email}):
        return resp(409, {"message":"이미 등록된 이메일입니다."})

    # 신규 사용자 저장 (프로덕션 → 비밀번호 해시!)
    table_user.put_item(Item={
        "email": email,
        "username": username,
        "password": password,
        "role": role
    })
    return resp(201, {"message":"회원가입 완료"})

# ────────────────────────────
# /login
# ────────────────────────────
def handle_login(event):
    # body 파싱
    body = json.loads(event.get("body") or "{}")
    email    = body.get("email")
    password = body.get("password")

    if not email or not password:
        return resp(400, {"message": "이메일과 비밀번호는 필수입니다."})

    # 사용자 조회
    try:
        result = table_user.get_item(Key={"email": email})
        user   = result.get("Item")
    except ClientError as ce:
        print("Dynamo error:", ce)
        return resp(500, {"message": "DB 조회 실패"})

    if not user:
        return resp(401, {"message": "존재하지 않는 사용자입니다."})

    # ***프로덕션에서는 해시 비교*** (여긴 평문 비교 예시)
    if user.get("password") != password:
        return resp(401, {"message": "비밀번호가 틀렸습니다."})

    return resp(200, {
        "message"      : "로그인 성공",
        "role"         : user.get("role", "staff"),
        "hospitalId"   : user.get("hospitalId", "H001"),
        "hospitalName" : user.get("hospitalName", "서울대병원")
    })

# ────────────────────────────
# /devicedata
# ────────────────────────────
def handle_devicedata(event):
    qs = event.get("queryStringParameters") or {}
    ek = qs.get("entityKey")
    if not ek:
        return resp(400, {"message": "entityKey 파라미터가 필요합니다."})

    start = qs.get("start", "1900-01-01T00:00")
    end   = qs.get("end"  , "9999-12-31T23:59")

    try:
        resp_items = table_data.query(
            KeyConditionExpression=Key("entityKey").eq(ek) &
                                   Key("timestamp").between(start, end),
            ScanIndexForward=False  # 최신순
        )
        items = resp_items.get("Items", [])
        return resp(200, {"count": len(items), "items": items})

    except ClientError as ce:
        print("Query error:", ce)
        return resp(500, {"message": "데이터 조회 실패"})
