import os
import json
import random
import time
from flask import Flask, request, jsonify

app = Flask(__name__)

BOT_TOKEN = os.getenv('8324651705:AAG6fyMu3E147XYcL8lp1xM8IoT8vadAc0E', '')
DATA_DIR = os.getenv('DATA_DIR', './data')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def file_path_for_mode(mode):
    safe = ''.join(c for c in mode if c.isalnum() or c in ['-', '_'])
    return os.path.join(DATA_DIR, f'history_{safe}.json')

def load_history(mode):
    path = file_path_for_mode(mode)
    if not os.path.isfile(path):
        return []
    with open(path, 'r') as f:
        try:
            return json.load(f)
        except:
            return []

def save_history(mode, data):
    # keep last 1000 entries
    data = data[-1000:]
    path = file_path_for_mode(mode)
    with open(path + '.tmp', 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(path + '.tmp', path)

def append_result(mode, period, number):
    history = load_history(mode)
    history.append({'period': period, 'number': number, 'time': int(time.time())})
    save_history(mode, history)

def predict_from_history(history):
    nums = [int(r['number']) for r in history]
    if not nums:
        num = random.randint(0,9)
        return {'number': num, 'bigsmall': 'Big' if num>=5 else 'Small', 'confidence': 0.15, 'explain': 'No history — random'}

    freq = {}
    for n in nums:
        freq[n] = freq.get(n,0) + 1

    most_common = max(freq, key=freq.get)
    most_common_count = freq[most_common]

    # Markov-like: next number freq after last
    trans = {}
    for i in range(len(nums)-1):
        a,b = nums[i], nums[i+1]
        if a not in trans:
            trans[a] = {}
        trans[a][b] = trans[a].get(b,0)+1

    last = nums[-1]
    if last in trans and trans[last]:
        candidate = max(trans[last], key=trans[last].get)
        succ_count = trans[last][candidate]
        total_succ = sum(trans[last].values())
        conf = min(0.95, 0.2 + (succ_count / total_succ) * 0.8)
        return {
            'number': candidate,
            'bigsmall': 'Big' if candidate>=5 else 'Small',
            'confidence': round(conf,3),
            'explain': f"Markov: last={last}, next_most={candidate} ({succ_count}/{total_succ})"
        }

    # fallback
    if random.randint(1,100) <= 70:
        conf = min(0.9, 0.15 + (most_common_count / max(1,len(nums))) * 0.85)
        return {
            'number': most_common,
            'bigsmall': 'Big' if most_common>=5 else 'Small',
            'confidence': round(conf,3),
            'explain': f"Fallback: most common ({most_common_count}/{len(nums)})"
        }
    else:
        pool = []
        for k,v in freq.items():
            pool.extend([k]*v)
        choice = random.choice(pool) if pool else random.randint(0,9)
        conf = round(min(0.85, 0.1 + (freq.get(choice,1) / max(1,len(nums)))*0.8),3)
        return {
            'number': choice,
            'bigsmall': 'Big' if choice>=5 else 'Small',
            'confidence': conf,
            'explain': "Weighted-random fallback"
        }

def send_telegram_message(chat_id, text):
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown'
    }
    resp = requests.post(url, json=data)
    return resp.json()

@app.route('/bot', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return 'ok'

    message = data.get('message') or data.get('edited_message')
    if not message:
        return 'ok'

    chat_id = message['chat']['id']
    text = message.get('text','').strip()
    if not text:
        return 'ok'

    parts = text.split()
    cmd = parts[0].lower()

    if cmd in ['/start', '/help']:
        reply = (
            "🤖 Prediction Bot\n"
            "Commands:\n"
            "/predict [30|60|180]\n"
            "/report <mode> <number>   (e.g. /report 60 7)\n"
            "/history [mode]\n\n"
            "Note: Add actual results via /report to improve predictions."
        )
        send_telegram_message(chat_id, reply)
        return 'ok'

    elif cmd == '/predict':
        mode = parts[1] if len(parts)>1 else '60'
        history = load_history(mode)
        pred = predict_from_history(history)
        periodLabel = time.strftime('%Y%m%d%H%M%S', time.gmtime())
        txt = (f"*Prediction* — mode: {mode}\n"
               f"Period: `{periodLabel}`\n"
               f"Number: *{pred['number']}* ({pred['bigsmall']})\n"
               f"Confidence: *{round(pred['confidence']*100,1)}%*\n"
               f"Explain: {pred['explain']}")
        send_telegram_message(chat_id, txt)
        return 'ok'

    elif cmd == '/report':
        if len(parts) == 3:
            mode = parts[1]
            try:
                number = int(parts[2])
            except:
                send_telegram_message(chat_id, "Number must be 0-9.")
                return 'ok'
        elif len(parts) == 2:
            mode = '60'
            try:
                number = int(parts[1])
            except:
                send_telegram_message(chat_id, "Number must be 0-9.")
                return 'ok'
        else:
            send_telegram_message(chat_id, "Usage: /report <mode> <number> or /report <number>")
            return 'ok'

        if not (0 <= number <=9):
            send_telegram_message(chat_id, "Number must be 0-9.")
            return 'ok'

        period = time.strftime('%Y%m%d%H%M%S', time.gmtime())
        append_result(mode, period, number)
        send_telegram_message(chat_id, f"Saved: mode {mode} period {period} => {number}")
        return 'ok'

    elif cmd == '/history':
        mode = parts[1] if len(parts)>1 else '60'
        h = load_history(mode)
        if not h:
            send_telegram_message(chat_id, f"No history for mode {mode}")
        else:
            last10 = h[-10:]
            lines = [f"{row['period']} => {row['number']}" for row in last10]
            send_telegram_message(chat_id, f"Last {len(last10)} results for {mode}:\n" + '\n'.join(lines))
        return 'ok'

    else:
        # unknown command ignore
        return 'ok'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)