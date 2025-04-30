import paho.mqtt.client as mqtt

import ssl

import json

import time

import random



# ==== ?ㅼ젙 ====

ENDPOINT = "a2m262usow07hn-ats.iot.ap-northeast-2.amazonaws.com"

CLIENT_ID = "GATEWAY-inst001-pi0001-p1002"

THING_NAME = "inst001-pi0001-p1002"



# ?몄쬆??寃쎈줈

CERT_PATH = "/home/capstone/aws-iot-certs/"



CA = CERT_PATH + "AmazonRootCA1.pem"

CERT = CERT_PATH + "04373bbf4f801f169ce1ffadffb37419ee0009f0630740774bf3dc91c8ebd18a-certificate.pem.crt"

KEY = CERT_PATH + "04373bbf4f801f169ce1ffadffb37419ee0009f0630740774bf3dc91c8ebd18a-private.pem.key"



# MQTT ?좏뵿

SHADOW_UPDATE = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update"

SHADOW_GET    = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/get"

SHADOW_DELTA  = f"$aws/things/{THING_NAME}/shadow/name/{CLIENT_ID}/update/delta"





# ==== 肄쒕갚 ?⑥닔 ====

def on_connect(client, userdata, flags, rc):

    print("MQTT ?곌껐 ?곹깭:", rc)

    client.subscribe(SHADOW_DELTA)

    client.subscribe(SHADOW_GET)





def on_message(client, userdata, msg):

    if msg.topic.endswith("update/delta"):

        payload = json.loads(msg.payload.decode())

        desired_raw = payload.get("state", {})  # ?닿쾶 delta ?곹깭 ?꾩껜

        

        desired = desired_raw.get("desired", desired_raw)  # 以묒꺽 諛⑹? 泥섎━



        print("?뱿 [desired] ?곹깭 蹂寃??붿껌:", desired)



        if "led" in desired:

            if desired["led"] == "on":

                print("?윟 LED ON")

            else:

                print("?ワ툘 LED OFF")



        # ?곹깭 ?숆린??
        client.publish(SHADOW_UPDATE, json.dumps({

            "state": {

                "reported": desired

            }

        }))





# ==== Shadow ?곹깭 ?낅뜲?댄듃 ?⑥닔 ====

def update_shadow(state_dict):

    payload = {

        "state": {

            "reported": state_dict

        }

    }

    client.publish(SHADOW_UPDATE, json.dumps(payload))

    print("?뱾 [reported] ?곹깭 ?꾩넚:", state_dict)





# ==== MQTT ?대씪?댁뼵???ㅼ젙 ====

client = mqtt.Client(client_id=CLIENT_ID)

client.tls_set(ca_certs=CA, certfile=CERT, keyfile=KEY, tls_version=ssl.PROTOCOL_TLSv1_2)

client.on_connect = on_connect

client.on_message = on_message



client.connect(ENDPOINT, 8883, 60)



# ==== ?ㅽ뻾 猷⑦봽 ====

client.loop_start()



try:

    while True:

        # ?쇱꽌 媛??앹꽦

        ultraSonic = random.randint(90, 120)

        fall = random.randint(0, 1)  # 0 or 1

        call = random.randint(0, 1)  # 0 or 1



        # Shadow ?낅뜲?댄듃

        update_shadow({

            "fall": fall,

            "call": call,

            "ultraSonic": ultraSonic

        })



        time.sleep(10)



except KeyboardInterrupt:

    print("醫낅즺??")

    client.loop_stop()

    client.disconnect()

