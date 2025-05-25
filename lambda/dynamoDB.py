# lambda_function.py  —  핸들러: lambda_function.lambda_handler
import json, os, boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

TABLE_NAME   = os.getenv("TABLE", "devicedata")         # 환경 변수로 넣어도 됨
REGION       = os.getenv("AWS_REGION", "ap-northeast-2")

dynamodb     = boto3.resource("dynamodb", region_name=REGION)
table        = dynamodb.Table(TABLE_NAME)

def lambda_handler(event, context):
    try:
        meth = event.get("httpMethod")
        path = event.get("resource")   # ★ HTTP API면 event["rawPath"] 사용

        if meth == "GET" and path == "/devicedata":
            params = event.get("queryStringParameters") or {}
            entity = params.get("entityKey")
            if not entity:
                return _resp(400, {"msg": "entityKey query string 필수"})

            # 날짜 범위 (YYYY-MM-DD) → ISO(YYYY-MM-DDThh:mm)
            start = (params.get("start") or "1900-01-01") + "T00:00"
            end   = (params.get("end")   or "9999-12-31") + "T23:59"

            items = _query(entity, start, end)
            return _resp(200, {"count": len(items), "items": items})

        return _resp(404, {"msg": "Not Found"})

    except Exception as e:
        print("ERROR:", e)
        return _resp(500, {"error": str(e)})

# ---------- 내부 함수 ----------
def _query(entity_key, start_iso, end_iso):
    """PK = entityKey, SK(timestamp) 범위 검색"""
    resp = table.query(
        KeyConditionExpression = Key("entityKey").eq(entity_key) &
                                 Key("timestamp").between(start_iso, end_iso)
    )
    return _dec_to_num(resp.get("Items", []))

def _dec_to_num(obj):
    """DynamoDB Decimal → int/float 변환"""
    if isinstance(obj, list):
        return [_dec_to_num(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _dec_to_num(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return obj

def _resp(code, body):
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "http://127.0.0.1:5500",  # 필요 시 도메인 변경
            "Access-Control-Allow-Methods": "GET,OPTIONS"
        },
        "body": json.dumps(body, ensure_ascii=False)
    }
