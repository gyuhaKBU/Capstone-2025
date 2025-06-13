# lambda_function.py – institution → 환자 + 최신 devicedata

import json, boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from typing import Any, Dict, List

# ────────────────────────────────────────────────────────────────────────────────
# DynamoDB 초기화
# ────────────────────────────────────────────────────────────────────────────────
dynamodb      = boto3.resource("dynamodb")
tbl_patient   = dynamodb.Table("patient")
tbl_devdata   = dynamodb.Table("devicedata")

# ────────────────────────────────────────────────────────────────────────────────
# 공통 유틸
# ────────────────────────────────────────────────────────────────────────────────
CORS_HEADERS: Dict[str, str] = {
    "Access-Control-Allow-Origin" : "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Content-Type"                : "application/json",
}

def _decimal(o: Any):
    """DynamoDB Decimal → int/float (JSON 직렬화용)"""
    if isinstance(o, Decimal):
        return int(o) if o % 1 == 0 else float(o)
    raise TypeError

def _resp(code: int, body: Any):
    return {
        "statusCode": code,
        "headers"    : CORS_HEADERS,
        "body"       : json.dumps(body, default=_decimal),
    }

# ────────────────────────────────────────────────────────────────────────────────
# Lambda 핸들러
# ────────────────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    # CORS pre‑flight
    if event.get("httpMethod") == "OPTIONS":
        return _resp(200, {"message": "CORS preflight OK"})

    qs = event.get("queryStringParameters") or {}
    inst_id: str | None = qs.get("institutionId")
    if not inst_id:
        return _resp(400, {"message": "institutionId 쿼리 파라미터 필요"})

    # ① 환자 목록 조회 (PK = institutionId, SK = patientId)
    try:
        p_resp = tbl_patient.query(
            KeyConditionExpression=Key("institutionId").eq(inst_id)
        )
    except Exception as e:
        return _resp(500, {"message": f"patient 조회 실패: {e}"})

    patients: List[Dict[str, Any]] = p_resp.get("Items", [])
    if not patients:
        return _resp(404, {"message": "해당 기관에 등록된 환자가 없습니다."})

    # ② 각 환자별 최신 devicedata 조회 (순차 방식)
    items: List[Dict[str, Any]] = []
    for p in patients:
        # entityKey = inst001#101#p001
        entity_key = f"{inst_id}#{p['roomNo']}#{p['patientId']}"
        d_resp = tbl_devdata.query(
            KeyConditionExpression=Key("entityKey").eq(entity_key),
            ScanIndexForward=False,
            Limit=1,
        )
        latest = d_resp.get("Items", [{}])[0]
        items.append({
            "patient"    : p,
            "latestData" : latest,
        })

    return _resp(200, {"count": len(items), "items": items})
