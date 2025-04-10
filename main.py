import os
import gspread
import schedule
import threading
import time
import logging
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify, abort
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, PushMessageRequest, TextMessage
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

# 設定
LINE_TOKEN = os.getenv("LINE_TOKEN")
LINE_SECRET = os.getenv("LINE_SECRET")

configuration = Configuration(access_token=LINE_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))
handler = WebhookHandler(LINE_SECRET)

SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
CREDS = ServiceAccountCredentials.from_json_keyfile_name('iconic-medium-credentials.json', SCOPE)
sheet = gspread.authorize(CREDS).open('糾察隊').sheet1

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "✅ LINE Bot Server is Live!"

@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    hash_obj = hmac.new(LINE_SECRET.encode('utf-8'), body.encode('utf-8'), hashlib.sha256)
    calculated_signature = base64.b64encode(hash_obj.digest()).decode('utf-8')
    if not hmac.compare_digest(calculated_signature, signature):
        abort(403)
    try:
        handler.handle(body, signature)
        return "OK"
    except InvalidSignatureError:
        abort(403)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@handler.add(MessageEvent)
def handle_message(event):
    if isinstance(event.message, TextMessageContent) and event.source.type == 'group':
        group_id = event.source.group_id
        with open('group_id.txt', 'w') as f:
            f.write(group_id)
        line_bot_api.reply_message(
            reply_token=event.reply_token,
            messages=[TextMessage(text=f"👥 已記錄群組 ID：{group_id}")]
        )

def push_line_message(text, to_id):
    try:
        message = TextMessage(text=text)
        request = PushMessageRequest(to=to_id, messages=[message])
        line_bot_api.push_message(push_message_request=request)
    except Exception as e:
        print(f"發送訊息失敗: {e}")

def send_today_message():
    try:
        with open('group_id.txt', 'r') as f:
            group_id = f.read().strip()
    except FileNotFoundError:
        return
    today = datetime.now().strftime('%Y/%m/%d')
    weekday = datetime.now().strftime('%A')
    if weekday in ['Saturday', 'Sunday']:
        return
    rows = sheet.get_all_records()
    for row in rows:
        if row['日期'] == today:
            message = "\n".join([f"{k}: {v}" for k, v in row.items() if k != '日期'])
            push_line_message(message, group_id)
            return
    push_line_message(f"今天是 {today}，無對應資料。", group_id)

def run_schedule():
    schedule.every().day.at("08:00").do(send_today_message)
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == '__main__':
    threading.Thread(target=run_schedule, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
