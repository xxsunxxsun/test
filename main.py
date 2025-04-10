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

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# ====== Google Sheets 設定 ======
SCOPE = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
CREDS = ServiceAccountCredentials.from_json_keyfile_name(
    'iconic-medium-452908-m1-9142065925d1.json', SCOPE)
client = gspread.authorize(CREDS)
sheet = client.open('糾察隊').sheet1

# ====== LINE 設定 ======
LINE_TOKEN = os.getenv('LINE_TOKEN')
LINE_SECRET = os.getenv('LINE_SECRET')

logger.info("初始化 LINE Bot...")
configuration = Configuration(access_token=LINE_TOKEN)
line_bot_api = MessagingApi(ApiClient(configuration))
handler = WebhookHandler(LINE_SECRET)
logger.info("LINE Bot 初始化完成")

# Google Sheets 測試
try:
    rows = sheet.get_all_records()
    logger.info("成功連接 Google Sheets")
except Exception as e:
    logger.error(f"Google Sheets 連接失敗: {str(e)}")

# LINE Bot 測試
try:
    profile = line_bot_api.get_bot_info()
    logger.info("成功連接 LINE Bot API")
except Exception as e:
    logger.error(f"LINE Bot API 連接失敗: {str(e)}")


def verify_signature(body, signature):
    """驗證 LINE 的簽名"""
    hash_obj = hmac.new(LINE_SECRET.encode('utf-8'), body.encode('utf-8'),
                        hashlib.sha256)
    calculated_signature = base64.b64encode(hash_obj.digest()).decode('utf-8')
    return hmac.compare_digest(calculated_signature, signature)


@app.route('/webhook', methods=['POST'])
def webhook():
    logger.info("收到 Webhook 請求")
    logger.info(f"Headers: {dict(request.headers)}")

    # 取得 X-Line-Signature header 值
    signature = request.headers.get('X-Line-Signature', '')
    logger.info(f"Signature: {signature}")

    # 取得請求內容
    body = request.get_data(as_text=True)
    logger.info(f"Body: {body}")

    # 驗證簽名
    if not verify_signature(body, signature):
        logger.error("簽名驗證失敗")
        return jsonify({
            'status': 'error',
            'message': 'Invalid signature'
        }), 403

    try:
        handler.handle(body, signature)
        logger.info("成功處理 Webhook 請求")
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"處理 Webhook 時發生錯誤：{str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    logger.info("收到訊息事件")
    try:
        if event.source.type == 'group':
            group_id = event.source.group_id
            logger.info(f"找到群組 ID：{group_id}")

            # 儲存群組 ID 到檔案
            with open('group_id.txt', 'w') as f:
                f.write(group_id)

            # 回覆訊息
            message = TextMessage(text=f"已成功取得群組 ID：{group_id}")
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[message]
                )
            )
            logger.info("已回覆群組 ID")
    except Exception as e:
        logger.error(f"處理訊息時發生錯誤：{str(e)}")


def send_today_message():
    logger.info("執行每日訊息發送")
    # 讀取儲存的群組 ID
    try:
        with open('group_id.txt', 'r') as f:
            group_id = f.read().strip()
    except FileNotFoundError:
        logger.error("尚未設定群組 ID")
        return

    today = datetime.now().strftime('%Y/%m/%d')
    weekday = datetime.now().strftime('%A')
    if weekday in ['Saturday', 'Sunday']:
        logger.info("週末不發送訊息")
        return

    rows = sheet.get_all_records()
    for row in rows:
        if row['日期'] == today:
            message = ""
            for class_name in row:
                if class_name != '日期':
                    message += f"{class_name}: {row[class_name]}\n"
            push_line_message(message.strip(), group_id)
            return
    push_line_message(f"今天是 {today}，但找不到對應訊息", group_id)


def run_schedule():
    """執行排程任務"""
    logger.info("啟動排程任務")
    while True:
        schedule.run_pending()
        time.sleep(60)


def push_line_message(text, to_id):
    try:
        from linebot.v3.messaging import TextMessage
        message = TextMessage(text=text)
        request = PushMessageRequest(
            to=to_id,
            messages=[message]
        )
        line_bot_api.push_message(push_message_request=request)
        logger.info(f"成功發送訊息到 {to_id}")
    except Exception as e:
        logger.error(f"發送訊息失敗: {str(e)}")


if __name__ == "__main__":
    logger.info("程式啟動")
    # 設定每天早上 8:00 發送訊息
    schedule.every().day.at("08:00").do(send_today_message)

    # 在背景執行排程
    schedule_thread = threading.Thread(target=run_schedule)
    schedule_thread.daemon = True
    schedule_thread.start()

    # 啟動 Flask 應用
    logger.info("啟動 Flask 應用")
    app.run(host='0.0.0.0', port=5000)
