from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.api import users_bp
from backend.models.user import User

def format_user(user):
    return {
        'id': user['id'],
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'email': user['email'],
        'mobile': user['mobile'],
        'role': user['role'],
        'avatar_path': user['avatar_path'],
        'job_count': user.get('job_count', 0),
        'created_at': user['created_at'].isoformat() if hasattr(user['created_at'], 'isoformat') else user['created_at'],
        'updated_at': user['updated_at'].isoformat() if hasattr(user['updated_at'], 'isoformat') else user['updated_at']
    }

def is_admin(user_id):
    user = User.find_by_id(user_id)
    return user and user.get('role') == 'admin'

@users_bp.route('', methods=['GET'])
@jwt_required()
def get_users():
    current_user_id = get_jwt_identity()
    
    if not is_admin(current_user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    users = User.get_all()
    formatted_users = [format_user(user) for user in users]
    
    return jsonify(formatted_users), 200

@users_bp.route('/<user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id != user_id and not is_admin(current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    user = User.find_by_id(user_id)
    
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify(format_user(user)), 200

@users_bp.route('', methods=['POST'])
@jwt_required()
def create_user():
    current_user_id = get_jwt_identity()
    
    if not is_admin(current_user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    data = request.get_json()
    
    required_fields = ['first_name', 'last_name', 'email', 'mobile', 'role', 'password']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    
    if data['role'] not in ['admin', 'employee']:
        return jsonify({'error': 'Role must be admin or employee'}), 400
    
    existing_user = User.find_by_email(data['email'])
    if existing_user:
        return jsonify({'error': 'Email already exists'}), 400
    
    try:
        user = User.create(
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            mobile=data['mobile'],
            role=data['role'],
            password=data['password'],
            avatar_path=data.get('avatar_path')
        )
        
        return jsonify(format_user(user)), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id != user_id and not is_admin(current_user_id):
        return jsonify({'error': 'Access denied'}), 403
    
    data = request.get_json()
    
    user = User.find_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    if 'role' in data and not is_admin(current_user_id):
        return jsonify({'error': 'Only admins can change roles'}), 403
    
    if data.get('role') and data['role'] not in ['admin', 'employee']:
        return jsonify({'error': 'Role must be admin or employee'}), 400
    
    if 'email' in data and data['email'] != user['email']:
        existing_user = User.find_by_email(data['email'])
        if existing_user:
            return jsonify({'error': 'Email already exists'}), 400
    
    try:
        updated_user = User.update(user_id, **data)
        
        if not updated_user:
            return jsonify({'error': 'Failed to update user'}), 500
        
        return jsonify(format_user(updated_user)), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<user_id>/password', methods=['PUT'])
@jwt_required()
def change_password(user_id):
    current_user_id = get_jwt_identity()
    
    if current_user_id != user_id:
        return jsonify({'error': 'You can only change your own password'}), 403
    
    data = request.get_json()
    
    if not data.get('new_password'):
        return jsonify({'error': 'New password is required'}), 400
    
    if len(data['new_password']) < 8:
        return jsonify({'error': 'Password must be at least 8 characters long'}), 400
    
    user = User.find_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        updated_user = User.update(user_id, password=data['new_password'])
        
        if not updated_user:
            return jsonify({'error': 'Failed to update password'}), 500
        
        return jsonify({'message': 'Password changed successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@users_bp.route('/<user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    current_user_id = get_jwt_identity()
    
    if not is_admin(current_user_id):
        return jsonify({'error': 'Admin access required'}), 403
    
    if current_user_id == user_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    user = User.find_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    try:
        success = User.delete(user_id)
        
        if success:
            return jsonify({'message': 'User deleted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to delete user'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
