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
        email = body.get('email')
        password = body.get('password')

        # 필수값 확인
        if not email or not password:
            return {
                'statusCode': 400,
                'headers': headers,
                'body': json.dumps({'message': '이메일과 비밀번호는 필수 항목입니다.'})
            }

        # DynamoDB에서 사용자 정보 조회
        response = table.get_item(Key={'email': email})
        
        if 'Item' not in response:
            return {
                'statusCode': 401,
                'headers': headers,
                'body': json.dumps({'message': '존재하지 않는 사용자입니다.'})
            }
        
        user = response['Item']
        
        # 비밀번호 검증
        if user['password'] != password:
            return {
                'statusCode': 401,
                'headers': headers,
                'body': json.dumps({'message': '비밀번호가 틀렸습니다.'})
            }
        
        # 로그인 성공
        user_role = user.get('role', 'staff')
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({
                'message': '로그인 성공',
                'role': user_role,
                'hospitalId': 'H001',
                'hospitalName': '서울대병원'
            })
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'message': f'오류 발생: {str(e)}'})
        }