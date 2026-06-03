from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

CLAUDE_KEY = os.getenv('CLAUDE_API_KEY')
FAL_KEY = os.getenv('FAL_API_KEY')

@app.route('/')
def home():
    return "AI Art Studio Backend is running! ✓"

@app.route('/api', methods=['POST', 'OPTIONS'])
def api():
    response = jsonify({})
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    
    if request.method == 'OPTIONS':
        return response
    
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'generate-prompts':
            description = data.get('description')
            ratio = data.get('ratio')
            
            resp = requests.post(
                'https://api.anthropic.com/v1/messages',
                headers={'Content-Type': 'application/json', 'x-api-key': CLAUDE_KEY, 'anthropic-version': '2023-06-01'},
                json={'model': 'claude-opus-4-1', 'max_tokens': 1024, 'messages': [{'role': 'user', 'content': f'Generate 4 unique wall art prompts. User: {description}. Ratio: {ratio}. Format: 4 prompts, one per line, no numbering.'}]},
                timeout=30
            )
            
            if resp.status_code == 200:
                data = resp.json()
                prompts = [p.strip() for p in data['content'][0]['text'].split('\n') if p.strip()][:4]
                result = jsonify({'prompts': prompts})
            else:
                result = jsonify({'error': 'Claude API error'}), 500
        
        elif action == 'generate-images':
            images = []
            for prompt in data.get('prompts', []):
                try:
                    resp = requests.post(
                        f'https://queue.fal.run/{data.get("model")}',
                        headers={'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'},
                        json={'prompt': prompt, 'image_size': 'landscape', 'num_inference_steps': 30},
                        timeout=60
                    )
                    if resp.status_code == 200 and resp.json().get('output', {}).get('image'):
                        images.append(resp.json()['output']['image']['url'])
                except:
                    pass
            result = jsonify({'images': images})
        
        elif action == 'remove-background':
            processed = []
            for url in data.get('image_urls', []):
                try:
                    resp = requests.post(
                        'https://queue.fal.run/fal-ai/bria/background/remove',
                        headers={'Authorization': f'Key {FAL_KEY}', 'Content-Type': 'application/json'},
                        json={'image_url': url},
                        timeout=60
                    )
                    if resp.status_code == 200 and resp.json().get('output', {}).get('image'):
                        processed.append(resp.json()['output']['image']['url'])
                    else:
                        processed.append(url)
                except:
                    processed.append(url)
            result = jsonify({'images': processed})
        
        else:
            result = jsonify({'error': 'Unknown action'}), 400
        
        if isinstance(result, tuple):
            response = result[0]
            status = result[1]
        else:
            response = result
            status = 200
        
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.status_code = status
        return response
    
    except Exception as e:
        result = jsonify({'error': str(e)})
        result.headers['Access-Control-Allow-Origin'] = '*'
        result.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        result.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        result.status_code = 500
        return result

if __name__ == '__main__':
    app.run()
