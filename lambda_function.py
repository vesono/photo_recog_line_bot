### line bot用lambda関数定義
# ライブラリ読みこみ 
import os
import datetime
from io import BytesIO
import boto3
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, ImageMessage

# s3設定
s3r = boto3.resource('s3')
bucket = s3r.Bucket('photo-recog-line-bot')
s3c = boto3.client('s3')

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

def lambda_handler(event, context):
    ### イベントごとに関数を定義
    # テキストメッセージの場合、オウム返しする
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(line_event):
        line_bot_api.reply_message(
            line_event.reply_token,
            TextSendMessage(text=line_event.message.text))
        # # s3保存処理(tmpにファイル作成 ⇒ s3に保存)
        # now = now_time()
        # name_tmpfile = now + '_lbot_text'
        # path_tmpfile = '/tmp/' + name_tmpfile + '.txt'
        # tmpfile = open(path_tmpfile,'w')
        # tmpfile.write(line_event.message.text)
        # tmpfile.close()
        # bucket.upload_file(path_tmpfile, 'test/' + name_tmpfile + '.txt')
        # # tmpファイル削除
        # os.remove(path_tmpfile)

    # 画像メッセージの場合は画像をs3に保存
    @handler.add(MessageEvent, message=ImageMessage)
    def handle_image(line_event):
        # 画像データを取得
        message_id = line_event.message.id
        message_content = line_bot_api.get_message_content(message_id)
        image_bin = BytesIO(message_content.content)
        image = image_bin.getvalue()
        # S3へ画像を保存
        now = now_time()
        s3_filepath = 'pic/' + now + '_lbot_image' + '.jpg'
        s3c.put_object(Bucket='photo-recog-line-bot', Body=image,  Key=s3_filepath)

    # debug
    print(event)

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