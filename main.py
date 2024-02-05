from flask import Flask, request, abort
import requests, os
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent, UnfollowEvent
from google.oauth2 import service_account
from googleapiclient.discovery import build
import gspread
import psycopg2
from psycopg2 import sql
from datetime import datetime, timedelta, timezone


# LINE botの設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

DATABASE_URL = os.environ['DATABASE_URL'] # PostgreSQLデータベースURLを取得
RENDER_APP_NAME = "line-hold" 

# Google Sheets APIの設定
SPREADSHEET_ID = os.environ['SPREADSHEET_ID']
spread_title = 'Sheet1'
SERVICE_ACCOUNT_FILE  = '/etc/secrets/credentials.json'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
gc = gspread.service_account(SERVICE_ACCOUNT_FILE)
worksheet = gc.open_by_key(SPREADSHEET_ID).worksheet(spread_title)

JST = timezone(timedelta(hours=+9), 'JST')
dt_now = datetime.now(JST)

app = Flask(__name__)
RENDER = "https://{}.onrender.com/".format(RENDER_APP_NAME)

header = {
    "Content_Type": "application/json",
    "Authorization": "Bearer " + LINE_CHANNEL_ACCESS_TOKEN
}

# スプレッドシートに書き込む関数
def append_data_to_spreadsheet(date, location, purpose, amount): 
    new_data = [date, location, purpose, amount]
    last_row = len(worksheet.col_values(1))
    worksheet.append_row(new_data, value_input_option='USER_ENTERED', insert_data_option='INSERT_ROWS', table_range=f'A{last_row+1}:D{last_row+1}')

# データベース接続
def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# データをデータベースに挿入
def insert_data(table_name, value):
    with get_connection() as conn:
        with conn.cursor() as cur:
            query = sql.SQL("INSERT INTO {} (date, location, purpose, amount) VALUES (%s, %s, %s, %s)").format(
                sql.Identifier(table_name)
                )
            cur.execute(query, value)

            conn.commit()

# ユーザごとの月の合計金額取得関数
def get_monthly_total(user_id):
    today = dt_now.date()
    start_of_month = today.replace(day=1)
    end_of_month = today.replace(day=1, month=today.month+1) - timedelta(days=1)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # user_idをテーブル名とする
            table_name = user_id
            # 月の合計金額を取得するSQLクエリ
            query = sql.SQL("SELECT SUM(amount) FROM {} WHERE date BETWEEN %s AND %s").format(
                sql.Identifier(table_name)
            )
            cur.execute(query, [start_of_month, end_of_month])
            total_amount = cur.fetchone()[0]
            return total_amount

# ユーザごとの月のタバコ合計金額取得関数
def get_monthly_cigarette_total(user_id):
    today = dt_now.date()
    start_of_month = today.replace(day=1)
    end_of_month = today.replace(day=1, month=today.month+1) - timedelta(days=1)

    with get_connection() as conn:
        with conn.cursor() as cur:
            # user_idをテーブル名とする
            table_name = user_id
            # 月の合計金額を取得するSQLクエリ
            query = sql.SQL("SELECT SUM(amount) FROM {} WHERE (date BETWEEN %s AND %s) AND purpose = 'タバコ'").format(
                sql.Identifier(table_name)
            )
            cur.execute(query, [start_of_month, end_of_month])
            total_cigarette_amount = cur.fetchone()[0]
            return total_cigarette_amount
        

@app.route("/")
def hello_world():
    return "hello world!"


# アプリにPOSTがあったときの処理
@app.route("/callback", methods=["POST"])
def callback():
    # get X-Line-Signature header value
    signature = request.headers["X-Line-Signature"]
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


# botにメッセージを送ったときの処理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    dt_now = datetime.now(JST)
    text = event.message.text.lower()
    profile = line_bot_api.get_profile(event.source.user_id)
    watabegg_id = 'Ub204e3d30a9ada4c261667699436afb6'

    if text == '合計':
        if profile.user_id == watabegg_id:
            total_amount = worksheet.acell('G3').value
        else:
            total_amount = get_monthly_total(profile.user_id)
        reply_message = f"今月の合計金額は{total_amount}円です。"
    elif text == 'タバコ合計':
        if profile.user_id == watabegg_id:
            cigarette_amount = worksheet.acell('J3').value
        else:
            cigarette_amount = get_monthly_cigarette_total(profile.user_id)
        reply_message = f"今月のタバコの合計金額は{cigarette_amount}円です。"
    elif ',' in text:
        try:
            text.replace(' ', '')
            date, location, purpose, amount = text.split(',')
            if date == '今日':
                date = dt_now.strftime('%Y/%m/%d')
            if profile.user_id == watabegg_id:
                append_data_to_spreadsheet(date, location, purpose, amount)
            else:
                value = [date, location, purpose, amount]
                insert_data(profile.user_id, value)
            reply_message = "家計簿に情報を追加しました。"
        except ValueError as e:
            reply_message = "入力エラー:入力が足りません。入力は「日付, 場所, 用途, 金額」のすべてを含んでください。"
    elif '、' in text:
        try:
            text.replace(' ', '')
            date, location, purpose, amount = text.split('、')
            if date == '今日':
                date = dt_now.strftime('%Y/%m/%d')
            if profile.user_id == watabegg_id:
                append_data_to_spreadsheet(date, location, purpose, amount)
            else:
                value = [date, location, purpose, amount]
                insert_data(profile.user_id, value)
            reply_message = "家計簿に情報を追加しました。"
        except ValueError as e:
            reply_message = "入力エラー:入力が足りません。入力は「日付, 場所, 用途, 金額」のすべてを含んでください。"
    else:
        reply_message = "入力エラー:入力は「日付, 場所, 用途, 金額」か「合計」、もしくは「タバコ合計」を入力してください"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_message)
    )


# botがフォローされたときの処理
@handler.add(FollowEvent)
def handle_follow(event):
    profile = line_bot_api.get_profile(event.source.user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            conn.autocommit = True
            # user_idをテーブル名とする
            table_name = profile.user_id
            # テーブルが存在しない場合のみ作成
            cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} (date DATE, location VARCHAR, purpose VARCHAR, amount INT)").format(
                sql.Identifier(table_name)
            ))
            conn.commit()


# botがアンフォロー(ブロック)されたときの処理
@handler.add(UnfollowEvent)
def handle_unfollow(event):
    profile = line_bot_api.get_profile(event.source.user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            conn.autocommit = True
            cur.execute('DROP TABLE IF EXISTS %s', profile.user_id)
    print("userIdの削除OK!!")


# アプリの起動
if __name__ == "__main__":

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
### End