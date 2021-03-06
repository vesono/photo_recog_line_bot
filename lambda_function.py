### line bot用lambda関数定義
# ライブラリ読みこみ 
import os
import datetime
import json
from decimal import *
import io
from io import BytesIO
from PIL import Image, ImageDraw, ExifTags, ImageColor
import boto3
from boto3.dynamodb.conditions import Key
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, FollowEvent, TextMessage, TextSendMessage, ImageMessage, ImageSendMessage

s3r = boto3.resource('s3')
s3c = boto3.client('s3')
s3_bucketname = 'photo-recog-line-bot'
s3_pub_bucketname = os.getenv('PUBLIC_S3_BUCKETNAME', None)
bucket = s3r.Bucket(s3_bucketname)
rekognition = boto3.client('rekognition')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('result_photo_linebot')

# LineBotApiインスタンスの作成
# CHANNEL_ACCESS_TOKEN: 各API通信を行うときに使用
# LINE_ACCESS_SECRET: 署名の検証で使用
channel_secret = os.getenv('LINE_ACCESS_SECRET', None)
channel_access_token = os.getenv('CHANNEL_ACCESS_TOKEN', None)
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

def now_time():
    """ ファイル名用日時取得関数

    Args:
        なし

    Returns:
        string: マイクロ秒を含めた20桁の数値を返す
    """
    now = datetime.datetime.today()
    return now.strftime("%Y%m%d%H%M%S") + str(now.microsecond)

# リプライ用テンプレート
reply_template = '''\
({11}色)
【性別】
    {0}
    (確率:{1}％)
【予想年齢】
    {2}歳
【感情分析】
  ・困惑:{3}％
  ・怒り:{4}％
  ・恐怖:{5}％
  ・驚き:{6}％
  ・喜び:{7}％
  ・悲しみ:{8}％
  ・穏やか:{9}％
  ・うんざり:{10}％'''

def template_rep(str_num, str, rep_str):
    """テンプレート置換関数

    Args:
        str_num (str): 置換位置を示す数値（文字で渡す）
        str (str): 置換対象文字列
        rep_str (str): 検索文字列

    Returns:
        string: 置換後の文字列を返す
    """
    str = str.replace('{' + str_num + '}', rep_str)
    return str

def lambda_handler(event, context):
    ### イベントごとに関数を定義
    # 友達追加時のイベント
    @handler.add(FollowEvent)
    def handle_follow(line_event):
        line_bot_api.reply_message(
            line_event.reply_token,
            TextSendMessage(text='友達追加ありがとう！'),
            TextSendMessage(text='写真を投稿すると諸々分析した結果が返ってくるよ！'))

    # テキストメッセージの場合、オウム返しする
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(line_event):
        line_bot_api.reply_message(
            line_event.reply_token,
            TextSendMessage(text=line_event.message.text))

    # 画像メッセージの場合の処理
    @handler.add(MessageEvent, message=ImageMessage)
    def handle_image(line_event):
        profile = line_bot_api.get_profile(line_event.source.user_id)
        # 画像データを取得
        message_id = line_event.message.id
        message_content = line_bot_api.get_message_content(message_id)
        image_bin = BytesIO(message_content.content)
        image = image_bin.getvalue()

        # s3へ画像を保存
        now = now_time()
        s3_filename = now + '_lbot_image'
        s3_filepath = 'pic/' + s3_filename + '.jpg'
        s3c.put_object(Bucket=s3_bucketname, Body=image, Key=s3_filepath)

        # rekognitionで画像認識
        response = rekognition.detect_faces(
                Image={
                    'S3Object': {
                        'Bucket': s3_bucketname,
                        'Name': s3_filepath,
                    }
                },
                Attributes=[
                    'ALL',
                ]
            )

        # CloudWatch出力
        print(response)

        # 写真に写る人数が3人以内の時にDB登録してレスポンスする
        if len(response['FaceDetails'])<=3 :
            # 画像処理
            pil_img = Image.open(image_bin)
            # サイズ取得
            imgWidth, imgHeight = pil_img.size
            # draw object作成
            draw = ImageDraw.Draw(pil_img)

            # json抽出、DynamoDB追加
            get_keys = ['BoundingBox', 'Gender', 'AgeRange', 'Smile', 'Emotions']
            face_index = 0
            for rtn_dict in response['FaceDetails']:
                # インクリメント、初期化
                face_index += 1
                rtn_text = {}

                # rekognitionの結果から必要な分だけ抽出
                for g_key in get_keys:
                    rtn_text[g_key] = rtn_dict[g_key]
            
                # DynamoDB登録
                # DynamoDB登録用にdict加工
                db_insert_json = {}
                db_insert_json['photo_name'] = s3_filename
                db_insert_json['No'] = face_index
                db_insert_json['userid'] = line_event.source.user_id
                db_insert_json['line_name'] = profile.display_name
                for key1 in rtn_text:
                    if  key1 == 'BoundingBox':
                        for key2 in rtn_text[key1]:
                            db_insert_json['BoundingBox' + '_' + key2] = rtn_text[key1][key2]
                    elif key1 == 'Gender':
                        for key2 in rtn_text[key1]:
                            if key2 == 'Value':
                                db_insert_json['Gender'] = rtn_text[key1][key2]
                            elif key2 == 'Confidence':
                                db_insert_json['Gender_prob'] = rtn_text[key1][key2]
                    elif key1 == 'AgeRange':
                        for key2 in rtn_text[key1]:
                            if key2 == 'Low':
                                db_insert_json['Age_low'] = rtn_text[key1][key2]
                            elif key2 == 'High':
                                db_insert_json['Age_high'] = rtn_text[key1][key2]
                    elif key1 == 'Smile':
                        for key2 in rtn_text[key1]:
                            if key2 == 'Value':
                                db_insert_json['Smile'] = rtn_text[key1][key2]
                            elif key2 == 'Confidence':
                                db_insert_json['Smile_prob'] = rtn_text[key1][key2]
                    elif key1 == 'Emotions':
                        for key2 in rtn_text[key1]:
                            db_insert_json[key2['Type']] = key2['Confidence']
                # Float to Decimal
                db_insert_json = json.loads(json.dumps(db_insert_json), parse_float=Decimal)
                # insert
                with table.batch_writer() as batch:
                    batch.put_item(Item=db_insert_json)
    
            # reply用list
            reply_list = []
            # DynamoDBより取得
            resp = table.query(KeyConditionExpression=Key('photo_name').eq(s3_filename))
            for item in resp['Items']:
                # テンプレート置換
                reply_text = reply_template
                gender_jpn = '男性' if item['Gender'] == 'Male' else '女性'
                reply_text = template_rep('0', reply_text, gender_jpn)
                reply_text = template_rep('1', reply_text, str(round(item['Gender_prob'], 2)))
                reply_text = template_rep('2', reply_text, str((item['Age_low'] + item['Age_high'])/2))
                reply_text = template_rep('3', reply_text, str(round(item['CONFUSED'], 2)))
                reply_text = template_rep('4', reply_text, str(round(item['ANGRY'], 2)))
                reply_text = template_rep('5', reply_text, str(round(item['FEAR'], 2)))
                reply_text = template_rep('6', reply_text, str(round(item['SURPRISED'], 2)))
                reply_text = template_rep('7', reply_text, str(round(item['HAPPY'], 2)))
                reply_text = template_rep('8', reply_text, str(round(item['SAD'], 2)))
                reply_text = template_rep('9', reply_text, str(round(item['CALM'], 2)))
                reply_text = template_rep('10', reply_text, str(round(item['DISGUSTED'], 2)))

                # image draw
                left = imgWidth * item['BoundingBox_Left']
                top = imgHeight * item['BoundingBox_Top']
                width = imgWidth * item['BoundingBox_Width']
                height = imgHeight * item['BoundingBox_Height']
                points = (
                    (left, top),
                    (left + width, top),
                    (left + width, top + height),
                    (left , top + height),
                    (left, top)
                )
                
                # 色わけ、値わけ
                if item['No'] == 1:
                    face_rekog_color = '赤'
                    draw.line(points, fill=(255, 0, 0), width=4)
                elif item['No'] == 2:
                    face_rekog_color = '緑'
                    draw.line(points, fill=(0, 255, 0), width=4)
                else:
                    face_rekog_color = '青'
                    draw.line(points, fill=(0, 0, 255), width=4)

                reply_text = template_rep('11', reply_text, face_rekog_color)
                reply_list.append(reply_text)

            # public権限でs3追加
            output = io.BytesIO()
            pil_img.save(output, format='JPEG')
            pub_image_value = output.getvalue()
            s3_pub_filename = now + '_lbot_image_pub.jpg'
            s3c.put_object(ACL='public-read', Bucket=s3_pub_bucketname, Body=pub_image_value, Key=s3_pub_filename)
            s3_pub_url = 'https://' + s3_pub_bucketname + '.s3-ap-northeast-1.amazonaws.com/' + s3_pub_filename

            # bot用リプライリスト作成
            reply_message_list = []
            reply_message_list.append(
                ImageSendMessage(
                        original_content_url=s3_pub_url,
                        preview_image_url=s3_pub_url
                ),
            )
            if len(response['FaceDetails'])==1:
                reply_message_list.append(TextSendMessage(text=reply_list[0]))
            elif len(response['FaceDetails'])==2:
                reply_message_list.append(TextSendMessage(text=reply_list[0]))
                reply_message_list.append(TextSendMessage(text=reply_list[1]))
            else:
                reply_message_list.append(TextSendMessage(text=reply_list[0]))
                reply_message_list.append(TextSendMessage(text=reply_list[1]))
                reply_message_list.append(TextSendMessage(text=reply_list[2]))
            print(reply_message_list)
            # リプライ処理
            line_bot_api.reply_message(
                reply_token=line_event.reply_token,
                messages=reply_message_list
            )
        else:
            # 4人以上の場合はs3から写真を削除
            s3c.delete_object(Bucket=s3_bucketname, Key=s3_filepath)
            # リプライ処理
            line_bot_api.reply_message(
                line_event.reply_token,
                TextSendMessage(text='写真に写る人数は3人以内に！'))

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