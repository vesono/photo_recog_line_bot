### line bot用lambda関数定義
# ライブラリ読みこみ 
import os
import datetime
import json
from io import BytesIO
import boto3
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

s3r = boto3.resource('s3')
bucket = s3r.Bucket('photo-recog-line-bot')
s3c = boto3.client('s3')
rekognition = boto3.client('rekognition')

# LineBotApiインスタンスの作成
# CHANNEL_ACCESS_TOKEN: 各API通信を行うときに使用
# LINE_ACCESS_SECRET: 署名の検証で使用
channel_secret = os.getenv('LINE_ACCESS_SECRET', None)
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN', None)
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# ファイル名用日時取得関数
def now_time():
    now = datetime.datetime.today()
    return now.strftime("%Y%m%d%H%M%S") + str(now.microsecond)

# メッセージ加工関数
def rtn_string(rp_key, detect_res):
    rtn_str = rp_key
    for item in detect_res[rp_key]:
        if type(detect_res[rp_key]) == dict:
            values = detect_res[rp_key][item]
            k_value = str(round(values, 2)) + '%' if type(values)==float else str(values)
            rtn_str = rtn_str + '\n' + '    ' + item + '：' + k_value
        else:
            for keys in item:
                values = item[keys]
                k_value = str(round(values, 2)) + '%' if type(values)==float else str(values)
                rtn_str = rtn_str + '\n' + '    ' + keys + '：' + k_value
    return rtn_str

# 日本語変換
def rep_jpn(text):
    jpn_txt = text
    jpn_txt = jpn_txt.replace('Value：', '')
    jpn_txt = jpn_txt.replace('Low', '')
    jpn_txt = jpn_txt.replace('Gender', '【性別予想】')
    jpn_txt = jpn_txt.replace('Female', '女性')
    jpn_txt = jpn_txt.replace('male', '男性')
    jpn_txt = jpn_txt.replace('AgeRange', '【年齢予想】')
    jpn_txt = jpn_txt.replace('Smile', '【笑顔？】')
    jpn_txt = jpn_txt.replace('Emotions', '【感情】')
    jpn_txt = jpn_txt.replace('Type：CONFUSED', '困惑')
    jpn_txt = jpn_txt.replace('Type：ANGRY', '怒り')
    jpn_txt = jpn_txt.replace('Type：FEAR', '恐怖')
    jpn_txt = jpn_txt.replace('Type：SURPRISED', '驚き')
    jpn_txt = jpn_txt.replace('Type：HAPPY', '喜び')
    jpn_txt = jpn_txt.replace('Type：SAD', '悲しみ')
    jpn_txt = jpn_txt.replace('Type：CALM', '穏やか')
    jpn_txt = jpn_txt.replace('Type：DISGUSTED', 'いらいら')
    jpn_txt = jpn_txt.replace('Confidence', '')
    return jpn_txt

def lambda_handler(event, context):
    ### イベントごとに関数を定義
    # テキストメッセージの場合、オウム返しする
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(line_event):
        line_bot_api.reply_message(
            line_event.reply_token,
            TextSendMessage(text=line_event.message.text))

    # 画像メッセージの場合は画像をs3に保存
    @handler.add(MessageEvent, message=ImageMessage)
    def handle_image(line_event):
        # 画像データを取得
        message_id = line_event.message.id
        message_content = line_bot_api.get_message_content(message_id)
        image_bin = BytesIO(message_content.content)
        image = image_bin.getvalue()
        # s3へ画像を保存
        now = now_time()
        s3_filepath = 'pic/' + now + '_lbot_image' + '.jpg'
        s3c.put_object(Bucket='photo-recog-line-bot', Body=image, Key=s3_filepath)
        # rekognitionで画像認識
        response = rekognition.detect_faces(
                Image={
                    'S3Object': {
                        'Bucket': 'photo-recog-line-bot',
                        'Name': s3_filepath,
                    }
                },
                Attributes=[
                    'ALL',
                ]
            )
        # リプライメッセージ作成
        rtn_dict = response['FaceDetails'][0]
        # CloudWatch出力
        print(s3_filepath)
        print(rtn_dict)
        get_keys = ['Gender', 'AgeRange', 'Smile', 'Emotions']
        rtn_text = {}
        for g_key in get_keys:
            rtn_text[g_key] = rtn_dict[g_key]
        rtn_text['AgeRange']['Low'] = int((rtn_text['AgeRange']['Low'] + rtn_text['AgeRange']['High']) / 2)
        del rtn_text['AgeRange']['High']
        rekog_return = rtn_string('Gender', rtn_text) + '\n' + rtn_string('AgeRange', rtn_text) + '\n' + \
                       rtn_string('Smile', rtn_text) + '\n' + rtn_string('Emotions', rtn_text)
        rekog_return_jpn = rep_jpn(rekog_return)
        # リプライ処理
        line_bot_api.reply_message(
            line_event.reply_token,
            TextSendMessage(text=rekog_return_jpn))


    ### レスポンスの関数呼び出しとリクエストの署名検証
    # get X-Line-Signature header value
    signature = event["headers"]["X-Line-Signature"]
    # get request body
    body = event["body"]

    try:
        # 署名を検証し、問題なければhandleに定義されている関数を呼び出す
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    # handleの処理を終えればOKを返す
    return 'OK'
  
# end of file