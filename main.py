from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"message": "Backend is running"})

@app.route('/api', methods=['POST'])
def api():
    return jsonify({"status": "API works"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
