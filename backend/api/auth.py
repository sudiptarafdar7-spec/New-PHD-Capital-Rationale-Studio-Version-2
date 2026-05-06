from flask import request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from backend.api import auth_bp
from backend.models.user import User

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400
    
    user = User.find_by_email(email)
    
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    if not User.verify_password(password, user['password_hash']):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    access_token = create_access_token(identity=user['id'])
    
    user_data = {
        'id': user['id'],
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'email': user['email'],
        'mobile': user['mobile'],
        'role': user['role'],
        'avatar_path': user['avatar_path'],
        'created_at': user['created_at'].isoformat() if hasattr(user['created_at'], 'isoformat') else user['created_at'],
        'updated_at': user['updated_at'].isoformat() if hasattr(user['updated_at'], 'isoformat') else user['updated_at']
    }
    
    return jsonify({
        'access_token': access_token,
        'user': user_data
    }), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    current_user_id = get_jwt_identity()
    user = User.find_by_id(current_user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    user_data = {
        'id': user['id'],
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'email': user['email'],
        'mobile': user['mobile'],
        'role': user['role'],
        'avatar_path': user['avatar_path'],
        'created_at': user['created_at'].isoformat() if hasattr(user['created_at'], 'isoformat') else user['created_at'],
        'updated_at': user['updated_at'].isoformat() if hasattr(user['updated_at'], 'isoformat') else user['updated_at']
    }
    
    return jsonify(user_data), 200

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify({'message': 'Successfully logged out'}), 200
