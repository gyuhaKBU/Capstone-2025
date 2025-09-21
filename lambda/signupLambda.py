import json
import boto3


# DynamoDB 리소스 생성
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('User')

def lambda_handler(event, context):
    # 모든 응답에 CORS 헤더 포함
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
        'Content-Type': 'application/json'
    }
    
    # OPTIONS 요청 처리 (CORS preflight)
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'message': 'CORS preflight'})
        }
    
    try:
        # API Gateway를 통해 전달된 JSON 문자열 파싱
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})

        # 클라이언트로부터 전달받은 값 추출
        username = body.get('username')
        email = body.get('email')
        password = body.get('password')
        role = body.get('role', 'staff')

        # 필수값 확인
        if not username or not email or not password:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'message': '사용자명, 이메일, 비밀번호는 필수 항목입니다.'})
            }

        # 중복 이메일 확인
        existing_user = table.get_item(Key={'email': email})
        if 'Item' in existing_user:
            return {
                'statusCode': 409,
                'headers': headers,
                'body': json.dumps({'message': '이미 등록된 이메일입니다.'})
            }

        # 새 사용자 등록
        table.put_item(Item={
            'email': email,
            'username': username,
            'password': password,  # 임시로 평문 저장 (나중에 해시화 필요)
            'role': role
        })

        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'message': '회원가입이 완료되었습니다.'})
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'message': f'오류 발생: {str(e)}'})
        }

