from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/')
def home():
    return jsonify({'message': 'Hello from Flask'})

@app.route('/api', methods=['POST'])
def api_test():
    return jsonify({'success': True, 'message': 'API works'})

if __name__ == '__main__':
    app.run()
