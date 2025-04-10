import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
import schedule
import time
import threading
from linebot.v3.messaging import (
    MessagingApi, 
    Configuration, 
    ApiClient,
    TextMessage,
    PushMessageRequest,
    ReplyMessageRequest
)
from linebot.v3.webhooks import (
    MessageEvent, 
    TextMessageContent
)
from linebot.v3.webhook import WebhookHandler
import json
import logging
import hmac
import hashlib
import base64

# ====== 日誌設定 ======
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== 載入環境變數 ======
load_dotenv()

app = Flask(__name__)

# ====== Google Sheets 設定 ======
SCOPE = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
credentials_json = os.getenv("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open('糾察隊').sheet1

# ====== LINE 設定 ======
LINE_TOKEN = os.getenv('LINE_TOKEN')
LINE_SECRET = os.getenv('LINE_SECRET')
configuration = Configuration(access_token=LINE_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))
handler = WebhookHandler(LINE_SECRET)

# ====== 測試連線狀態 ======
try:
    sheet.get_all_records()
    logger.info("✅ 成功連接 Google Sheets")
except Exception as e:
    logger.error(f"❌ Google Sheets 錯誤: {str(e)}")

try:
    profile = line_bot_api.get_bot_info()
    logger.info("✅ 成功連接 LINE Bot API")
except Exception as e:
    logger.error(f"❌ LINE Bot 錯誤: {str(e)}")


def verify_signature(body, signature):
    hash_obj = hmac.new(LINE_SECRET.encode('utf-8'), body.encode('utf-8'), hashlib.sha256)
    calculated_signature = base64.b64encode(hash_obj.digest()).decode('utf-8')
    return hmac.compare_digest(calculated_signature, signature)


@app.route('/webhook', methods=['POST'])
def webhook():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    if not verify_signature(body, signature):
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 403

    try:
        handler.handle(body, signature)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        if event.source.type == 'group':
            group_id = event.source.group_id
            with open('group_id.txt', 'w') as f:
                f.write(group_id)
            message = TextMessage(text=f"✅ 已取得群組 ID：{group_id}")
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[message]
                )
            )
    except Exception as e:
        logger.error(f"處理訊息錯誤：{str(e)}")


def push_line_message(text, to_id):
    try:
        message = TextMessage(text=text)
        request = PushMessageRequest(to=to_id, messages=[message])
        line_bot_api.push_message(push_message_request=request)
        logger.info(f"✅ 發送成功至 {to_id}")
    except Exception as e:
        logger.error(f"❌ 發送訊息錯誤: {str(e)}")


def send_today_message():
    logger.info("🕗 檢查是否有訊息要發送")
    try:
        with open('group_id.txt', 'r') as f:
            group_id = f.read().strip()
    except FileNotFoundError:
        logger.error("❌ 尚未設定群組 ID")
        return

    today = datetime.now().strftime('%Y/%m/%d')
    weekday = datetime.now().strftime('%A')
    if weekday in ['Saturday', 'Sunday']:
        logger.info("🛌 週末不發送")
        return

    rows = sheet.get_all_records()
    for row in rows:
        if row['日期'] == today:
            message = "\n".join([f"{k}: {v}" for k, v in row.items() if k != '日期'])
            push_line_message(message.strip(), group_id)
            return
    push_line_message(f"今天是 {today}，但找不到對應訊息", group_id)


def run_schedule():
    schedule.every().day.at("08:00").do(send_today_message)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    logger.info("🚀 Flask 啟動中...")
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.daemon = True
    schedule_thread.start()
    app.run(host='0.0.0.0', port=5000)
