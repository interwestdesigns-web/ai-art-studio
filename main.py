from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS, GET'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Get API keys from environment variables
CLAUDE_KEY = os.getenv('CLAUDE_API_KEY')
FAL_KEY = os.getenv('FAL_API_KEY')

@app.route('/')
def home():
    return "AI Art Studio Backend is running! ✓"

@app.route('/api', methods=['POST', 'OPTIONS'])
def api():
    """Main API endpoint that dispatches based on action"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.json
        action = data.get('action')
        
        if action == 'generate-prompts':
            return generate_prompts(data)
        elif action == 'generate-images':
            return generate_images(data)
        elif action == 'remove-background':
            return remove_background(data)
        else:
            return jsonify({'error': f'Unknown action: {action}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_prompts(data):
    """Generate image prompts using Claude API"""
    try:
        description = data.get('description')
        ratio = data.get('ratio')
        
        if not description or not ratio:
            return jsonify({'error': 'Missing description or ratio'}), 400
        
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
                    'content': f'''Generate 4 unique, detailed image generation prompts for creating beautiful wall art.

User description: {description}
Aspect ratio: {ratio}

Each prompt should:
- Be specific and detailed (2-3 sentences)
- Include style, mood, and technical details
- Be optimized for AI image generation

Format: Just list 4 prompts, one per line, no numbering.'''
                }]
            }
        )
        
        if response.status_code != 200:
            return jsonify({'error': f'Claude API error: {response.text}'}), 500
        
        result = response.json()
        prompts = [p.strip() for p in result['content'][0]['text'].split('\n') if p.strip()][:4]
        
        return jsonify({'prompts': prompts})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def generate_images(data):
    """Generate images using fal.ai"""
    try:
        prompts = data.get('prompts', [])
        model = data.get('model')
        ratio = data.get('ratio')
        
        if not prompts or not model:
            return jsonify({'error': 'Missing prompts or model'}), 400
        
        generated_images = []
        
        for prompt in prompts:
            try:
                response = requests.post(
                    f'https://queue.fal.run/{model}',
                    headers={
                        'Authorization': f'Key {FAL_KEY}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'prompt': prompt,
                        'image_size': 'landscape' if 'Landscape' in ratio else 'portrait',
                        'num_inference_steps': 30
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('output') and result['output'].get('image'):
                        generated_images.append(result['output']['image']['url'])
            except Exception as e:
                print(f"Error generating image: {e}")
                continue
        
        return jsonify({'images': generated_images})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def remove_background(data):
    """Remove background from image using Bria RMBG"""
    try:
        image_urls = data.get('image_urls', [])
        
        if not image_urls:
            return jsonify({'error': 'Missing image_urls'}), 400
        
        processed_images = []
        
        for image_url in image_urls:
            try:
                response = requests.post(
                    'https://queue.fal.run/fal-ai/bria/background/remove',
                    headers={
                        'Authorization': f'Key {FAL_KEY}',
                        'Content-Type': 'application/json'
                    },
                    json={'image_url': image_url}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get('output') and result['output'].get('image'):
                        processed_images.append(result['output']['image']['url'])
                    else:
                        processed_images.append(image_url)
            except Exception as e:
                print(f"Error removing background: {e}")
                processed_images.append(image_url)
        
        return jsonify({'images': processed_images})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run()
