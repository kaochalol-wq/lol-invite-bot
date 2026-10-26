import sys
import time
import webbrowser
import keyring
from urllib.parse import urlparse

import pyperclip
import requests

CLIENT_ID = "qgyb52al6uft8geq9kc3bhkhqnvmd8"
TOKEN_SERVICE = "TwitchLobbyBotPublic"

INVITE_DOMAIN = "gg.riotgames.com"


def is_official_twitch_url(url):
try:
parsed = urlparse(url)
host = (parsed.hostname or "").lower()
return parsed.scheme == "https" and (
host == "twitch.tv" or host.endswith(".twitch.tv")
)
except ValueError:
return False


def logout():
existed = keyring.get_password(TOKEN_SERVICE, "refresh_token") is not None

try:
keyring.delete_password(TOKEN_SERVICE, "refresh_token")
except keyring.errors.PasswordDeleteError:
pass

if existed:
print("保存済みの認証情報を削除しました。")
else:
print("保存済みの認証情報はありませんでした。")

print(
"サーバー側でも完全に失効させるには、ブラウザでTwitchの"
"「設定 > 接続」を開き、このアプリの接続を切断してください。"
)


def authenticate():
service = TOKEN_SERVICE
client_id = CLIENT_ID

if not client_id:
raise SystemExit("CLIENT_IDを設定してください。")

refresh_token = keyring.get_password(service, "refresh_token")
print("保存済みトークンあり:", bool(refresh_token))
access_token = None

# 保存済みトークンで接続を試す
if refresh_token:
print("保存済みの認証情報で接続します...")

try:
response = requests.post(
"https://id.twitch.tv/oauth2/token",
data={
"client_id": client_id,
"grant_type": "refresh_token",
"refresh_token": refresh_token,
},
timeout=20,
)
except requests.RequestException as error:
raise SystemExit(f"Twitchへの接続に失敗しました: {error}")

if response.ok:
token_data = response.json()
access_token = token_data["access_token"]
new_refresh_token = token_data.get("refresh_token")

if new_refresh_token:
keyring.set_password(
service, "refresh_token", new_refresh_token
)
else:
# 新しい更新トークンが返らなくても、レスポンス本文には
# トークン自体が含まれるため表示しない。
# 保存済みの更新トークンは消さず、そのまま保持する。
print(
"新しい更新トークンは返されませんでしたが、"
"保存済みのものをそのまま使います。"
)
else:
# 失効・期限切れなど。理由はステータスコードだけを表示し、
# 使えなくなった保存済みトークンを消して再認証へ進む。
print(
"保存済みの認証情報では接続できませんでした "
f"(HTTP {response.status_code})。再認証します。"
)
try:
keyring.delete_password(service, "refresh_token")
except keyring.errors.PasswordDeleteError:
pass

# 初回、またはトークンが無効な場合はデバイス認証
if not access_token:
print("\n=== Twitch認証 ===")

scopes = "user:write:chat"

response = requests.post(
"https://id.twitch.tv/oauth2/device",
data={
"client_id": client_id,
"scopes": scopes,
},
timeout=20,
)
response.raise_for_status()
device = response.json()

device_code = device["device_code"]
user_code = device["user_code"]
verification_uri = device["verification_uri"]
interval = device.get("interval", 5)
expires_in = device.get("expires_in", 1800)

# 想定外のURLが返ってきた場合は、フィッシング防止のため開かない
if not is_official_twitch_url(verification_uri):
raise SystemExit(
"想定外の認証URLが返されました。安全のため中断します: "
f"{verification_uri}"
)

print("\n次のURLをブラウザで開いてください:")
print(verification_uri)
print("\n認証コード:", user_code)
print("Twitchでコードを入力し、アクセスを許可してください。")
print()
print("")
print("・このコードは、いまこのPCであなた自身が起動した認証用です。")
print("・他人から送られてきたコードは絶対に入力しないでください。")
print(
"・許可の前に、認証画面でアプリ名と権限が"
"「チャットへの書き込み」だけになっているか確認してください。"
)

webbrowser.open(verification_uri)

deadline = time.time() + expires_in
token_data = None

while time.time() < deadline:
time.sleep(interval)

response = requests.post(
"https://id.twitch.tv/oauth2/token",
data={
"client_id": client_id,
"scopes": scopes,
"device_code": device_code,
"grant_type":
"urn:ietf:params:oauth:grant-type:device_code",
},
timeout=20,
)

if response.ok:
token_data = response.json()
break

try:
message = response.json().get("message", "")
except ValueError:
message = ""

if message == "authorization_pending":
continue

if message == "slow_down":
interval += 5
continue

if message in ("expired_token", "invalid device code"):
break

raise SystemExit(
f"Twitch認証エラー: HTTP {response.status_code} "
f"{message or '詳細不明'}"
)

if not token_data:
raise SystemExit(
"認証が完了しませんでした。もう一度起動してください。"
)

access_token = token_data["access_token"]
refresh_token = token_data.get("refresh_token")

if not refresh_token:
raise SystemExit("更新用トークンを取得できませんでした。")

keyring.set_password(service, "refresh_token", refresh_token)
print("認証情報をWindowsの資格情報保管庫に保存しました。")

headers = {
"Client-Id": client_id,
"Authorization": f"Bearer {access_token}",
}

user_response = requests.get(
"https://api.twitch.tv/helix/users",
headers=headers,
timeout=20,
)
user_response.raise_for_status()
user = user_response.json()["data"][0]

print(f"認証成功: {user['login']}")
return headers, user["id"]


def is_lol_invite(text):
try:
parsed = urlparse(text.strip())
host = (parsed.hostname or "").lower()

return (
parsed.scheme == "https"
and (
host == INVITE_DOMAIN
or host.endswith("." + INVITE_DOMAIN)
)
)
except ValueError:
return False


def post_to_chat(headers, user_id, message):
response = requests.post(
"https://api.twitch.tv/helix/chat/messages",
headers={
**headers,
"Content-Type": "application/json",
},
json={
"broadcaster_id": user_id,
"sender_id": user_id,
"message": message,
},
timeout=20,
)

if response.ok:
data = response.json().get("data") or []
result = data[0] if data else {}
if result.get("is_sent"):
print("Twitchチャットへ投稿しました。")
else:
print("投稿できませんでした:", result.get("drop_reason"))
else:
print("投稿エラー:", response.status_code, response.text)


def main():
if "--logout" in sys.argv:
logout()
return

headers, user_id = authenticate()

previous = pyperclip.paste()

print("\n=== LoL招待リンク監視中 ===")
print("LoLで「招待リンクをコピー」を押してください。")
print("終了するには Ctrl+C を押します。")
print("認証情報を削除するには、--logout を付けて起動してください。")

while True:
text = pyperclip.paste()

if text!= previous:
previous = text
print("\nクリップボードが変更されました")

if is_lol_invite(text):
link = text.strip()
print("LoL招待リンクを検知しました:")
print(link)
post_to_chat(headers, user_id, link)
else:
print("今回は招待リンクとして認識されませんでした")

time.sleep(0.5)


if __name__ == "__main__":
try:
main()
except KeyboardInterrupt:
print("\n監視を終了しました。")
except requests.RequestException as error:
print("\n通信エラー:", error)
