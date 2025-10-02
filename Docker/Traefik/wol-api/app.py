from flask import Flask, request, jsonify
from wakeonlan import send_magic_packet

app = Flask(__name__)

@app.route('/wol', methods=['POST'])
def wol():
    data = request.get_json() or {}
    mac = data.get('mac')
    broadcast = data.get('broadcast', '192.168.1.255')  # Default broadcast
    
    if not mac:
        return jsonify({'error': 'mac address required'}), 400
    
    try:
        if broadcast:
            send_magic_packet(mac, ip_address=broadcast)
        else:
            send_magic_packet(mac)
        return jsonify({'status': 'sent', 'mac': mac, 'broadcast': broadcast})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})
if __name__ == '__main__':
	app.run(host='0.0.0.0', port=5000)