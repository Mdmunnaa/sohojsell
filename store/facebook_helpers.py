# ============================================================
# store/facebook_helpers.py
# Facebook API helper functions
# ============================================================
import requests

GRAPH_API = "https://graph.facebook.com/v21.0"


def get_fb_locale(request):
    """allauth-এর জন্য locale function"""
    return 'en_US'


def get_user_pages(user_access_token):
    """
    ইউজারের সব Facebook Page-এর লিস্ট আনবে।
    Return: list of dicts → [{id, name, access_token, picture}, ...]
    """
    url = f"{GRAPH_API}/me/accounts"
    params = {
        'access_token': user_access_token,
        'fields': 'id,name,access_token,picture,fan_count,category',
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        if 'data' in data:
            return data['data']
        return []
    except Exception:
        return []


def get_long_lived_token(short_lived_token, app_id, app_secret):
    """
    Short-lived token → Long-lived token (60 দিনের জন্য valid)
    allauth থেকে যে token আসে সেটা short-lived, এটা long-lived করতে হবে
    """
    url = f"{GRAPH_API}/oauth/access_token"
    params = {
        'grant_type': 'fb_exchange_token',
        'client_id': app_id,
        'client_secret': app_secret,
        'fb_exchange_token': short_lived_token,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        return data.get('access_token', short_lived_token)
    except Exception:
        return short_lived_token


def get_page_long_lived_token(page_id, user_long_lived_token):
    """
    Page-এর permanent token আনবে
    Page token কখনো expire হয় না (ব্যবহারকারী remove না করলে)
    """
    url = f"{GRAPH_API}/{page_id}"
    params = {
        'fields': 'access_token',
        'access_token': user_long_lived_token,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        return data.get('access_token', '')
    except Exception:
        return ''


def send_messenger_message(page_access_token, recipient_psid, text):
    """
    Facebook Page Inbox-এ মেসেজ পাঠাবে
    """
    url = f"{GRAPH_API}/me/messages"
    payload = {
        "recipient": {"id": recipient_psid},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    try:
        response = requests.post(
            url,
            json=payload,
            params={"access_token": page_access_token},
            timeout=10
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}
