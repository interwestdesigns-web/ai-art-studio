from flask import Flask, request, jsonify
import requests
import os
from flask_cors import CORS

app = Flask(__name__)

CORS(app, 
     origins=["*"],
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=False)

CLAUDE_KEY = os.getenv('CLAUDE_API_KEY')
FAL_KEY = os.getenv('FAL_API_KEY')

@app.route('/')
def home():
    return "AI Art Studio Backend is running! ✓"

@app.route('/api', methods=['POST', 'OPTIONS'])
def api():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'generate-prompts':
            description = data.get('description')
            ratio = data.get('ratio')
            
            response = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={
                    'Content-Type': 'application/json',
                    'x-api-key': CLAUDE_KEY,
                    'anthropic-version': '2023-06-01'
                },
                json={
                    'model': 'claude-opus-4-1',
                    'max_tokens': 1024,
                    'messages': [{
                        'role': 'user',
                        'content': f'Generate 4 prompts for wall art. User: {description}. Ratio: {ratio}. Format: one per line.'
                    }]
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                prompts = [p.strip() for p in data['content'][0]['text'].split('\n') if p.strip()][:4]
                return jsonify({'prompts': prompts})
            return jsonify({'error': 'Claude API error'}), 500
        
        elif action == 'generate-images':
            prompts = data.get('prompts', [])
            model = data.get('model')
            images = []
            
            for prompt in prompts:
                try:
                    resp = requests.post(
                        f'https://queue.fal.run/{model}',
                        headers={'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'},
                        json={'prompt': prompt, 'image_size': 'landscape', 'num_inference_steps': 30},
                        timeout=60
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result.get('output', {}).get('image'):
                            images.append(result['output']['image']['url'])
                except:
                    pass
            
            return jsonify({'images': images})
        
        elif action == 'remove-background':
            image_urls = data.get('image_urls', [])
            processed = []
            
            for url in image_urls:
                try:
                    resp = requests.post(
                        'https://queue.fal.run/fal-ai/bria/background/remove',
                        headers={'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'},
                        json={'image_url': url},
                        timeout=60
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result.get('output', {}).get('image'):
                            processed.append(result['output']['image']['url'])
                        else:
                            processed.append(url)
                except:
                    processed.append(url)
            
            return jsonify({'images': processed})
        
        return jsonify({'error': 'Unknown action'}), 400
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run()
