from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.api import api_keys_bp
from datetime import datetime
import os
import json

def get_current_user():
    user_id = get_jwt_identity()
    with get_db_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return user

def format_api_key(row):
    return {
        'id': row['id'],
        'provider': row['provider'],
        'value': row['key_value'],
        'created_at': row['created_at'].isoformat() if row['created_at'] else None,
        'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
    }

@api_keys_bp.route('', methods=['GET'])
@jwt_required()
def get_api_keys():
    """Get all API keys as an array of objects"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM api_keys ORDER BY provider")
            keys = cursor.fetchall()
            
            # Format as array of key objects
            result = [format_api_key(key) for key in keys]
            return jsonify(result), 200
                
    except Exception as e:
        print(f"Error getting API keys: {e}")
        return jsonify({'error': str(e)}), 500

@api_keys_bp.route('', methods=['PUT'])
@jwt_required()
def update_api_key():
    """Insert or update a single API key (UPSERT)"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json()
        provider = data.get('provider')
        value = data.get('value')
        
        if not provider:
            return jsonify({'error': 'Provider is required'}), 400
        
        # No hardcoded whitelist - accept any provider name for extensibility
        if not isinstance(provider, str) or len(provider) == 0 or len(provider) > 50:
            return jsonify({'error': 'Provider must be a non-empty string (max 50 characters)'}), 400
        
        with get_db_cursor(commit=True) as cursor:
            # UPSERT: Insert or update if provider exists
            cursor.execute("""
                INSERT INTO api_keys (provider, key_value, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (provider) 
                DO UPDATE SET 
                    key_value = EXCLUDED.key_value,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, (provider, value, datetime.now(), datetime.now()))
            
            updated_key = cursor.fetchone()
            return jsonify(format_api_key(updated_key)), 200
            
    except Exception as e:
        print(f"Error updating API key: {e}")
        return jsonify({'error': str(e)}), 500

@api_keys_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_google_cloud_json():
    """Upload Google Cloud JSON file and store file path in database"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if not file.filename or file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.json'):
            return jsonify({'error': 'Only JSON files are allowed'}), 400
        
        # Read and validate JSON content
        try:
            content = file.read()
            json_data = json.loads(content)
        except json.JSONDecodeError:
            return jsonify({'error': 'Invalid JSON file'}), 400
        
        # Create directory if it doesn't exist
        upload_dir = 'backend/api_keys'
        os.makedirs(upload_dir, exist_ok=True)
        
        # Save file with fixed name
        file_path = os.path.join(upload_dir, 'google-cloud.json')
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Store file path in database
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO api_keys (provider, key_value, created_at, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (provider) 
                DO UPDATE SET 
                    key_value = EXCLUDED.key_value,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, ('google_cloud', file_path, datetime.now(), datetime.now()))
            
            updated_key = cursor.fetchone()
            return jsonify(format_api_key(updated_key)), 200
            
    except Exception as e:
        print(f"Error uploading Google Cloud JSON: {e}")
        return jsonify({'error': str(e)}), 500

@api_keys_bp.route('/<provider>', methods=['DELETE'])
@jwt_required()
def delete_api_key(provider):
    """Delete a specific API key"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        # No hardcoded whitelist - accept any provider name for extensibility
        if not isinstance(provider, str) or len(provider) == 0 or len(provider) > 50:
            return jsonify({'error': 'Provider must be a non-empty string (max 50 characters)'}), 400
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM api_keys WHERE provider = %s RETURNING *", (provider,))
            deleted_key = cursor.fetchone()
            
            if not deleted_key:
                return jsonify({'error': 'API key not found'}), 404
            
            # If Google Cloud, also delete the file
            if provider == 'google_cloud' and deleted_key['key_value']:
                file_path = deleted_key['key_value']
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            return jsonify({'message': f'{provider} API key deleted successfully'}), 200
            
    except Exception as e:
        print(f"Error deleting API key: {e}")
        return jsonify({'error': str(e)}), 500
