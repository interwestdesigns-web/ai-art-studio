from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api', methods=['POST'])
def api():
    return jsonify({'test': 'working'})

if __name__ == '__main__':
    app.run()
