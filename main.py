from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app)

CLAUDE_KEY = os.getenv('CLAUDE_API_KEY')
FAL_KEY = os.getenv('FAL_API_KEY')

@app.route('/')
def home():
    return "AI Art Studio Backend is running! ✓"

@app.route('/api', methods=['POST'])
def api_endpoint():
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'generate-prompts':
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'Content-Type': 'application/json', 'x-api-key': CLAUDE_KEY, 'anthropic-version': '2023-06-01'},
                json={'model': 'claude-opus-4-1', 'max_tokens': 1024, 'messages': [{'role': 'user', 'content': f'Generate 4 wall art prompts for {data.get("description")} in {data.get("ratio")} ratio. Output: 4 prompts, one per line.'}]},
                timeout=30
            )
            if resp.status_code == 200:
                prompts = [p.strip() for p in resp.json()['content'][0]['text'].split('\n') if p.strip()][:4]
                return jsonify({'prompts': prompts})
            return jsonify({'error': 'Claude API failed'}), 500
        
        elif action == 'generate-images':
            images = []
            for prompt in data.get('prompts', []):
                try:
                    r = requests.post(f"https://queue.fal.run/{data.get('model')}", headers={'Authorization': f"Key {FAL_KEY}", 'Content-Type': 'application/json'}, json={'prompt': prompt, 'image_size': 'landscape', 'num_inference_steps': 30}, timeout=60)
                    if r.status_code == 200 and r.json().get('output', {}).get('image'):
                        images.append(r.json()['output']['image']['url'])
                except: pass
            return jsonify({'images': images})
        
        elif action == 'remove-background':
            images = []
            for url in data.get('image_urls', []):
                try:
                    r = requests.post('https://queue.fal.run/fal-ai/bria/background/remove', headers={'Authorization': f"Key {FAL_KEY}", 'Content-Type': 'application/json'}, json={'image_url': url}, timeout=60)
                    if r.status_code == 200 and r.json().get('output', {}).get('image'):
                        images.append(r.json()['output']['image']['url'])
                    else:
                        images.append(url)
                except: images.append(url)
            return jsonify({'images': images})
        
        return jsonify({'error': 'Unknown action'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run()
