from flask import request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.api import channels_bp
from backend.models.user import User
from werkzeug.utils import secure_filename
import os
import uuid
import mimetypes
from datetime import datetime

LOGO_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'channel_logos')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_admin(user_id):
    user = User.find_by_id(user_id)
    return user and user.get('role') == 'admin'

def get_file_size_string(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

@channels_bp.route('', methods=['GET'])
@jwt_required()
def get_channels():
    try:
        current_user_id = get_jwt_identity()
        
        if not is_admin(current_user_id):
            return jsonify({'error': 'Admin access required'}), 403
        
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, channel_name, channel_logo_path, channel_url, platform, added_at, updated_at
                FROM channels
                ORDER BY added_at DESC
            """)
            channels = cursor.fetchall()
            
            channels_list = []
            for channel in channels:
                logo_url = f"/api/v1/channels/{channel['id']}/logo" if channel['channel_logo_path'] else ''
                channels_list.append({
                    'id': channel['id'],
                    'channel_name': channel['channel_name'],
                    'name': channel['channel_name'],
                    'logoPath': logo_url,
                    'channelLink': channel['channel_url'] or '',
                    'channel_url': channel['channel_url'] or '',
                    'platform': channel.get('platform', 'youtube'),
                    'addedAt': channel['added_at'].isoformat() if channel['added_at'] else ''
                })
            
            return jsonify(channels_list), 200
    
    except Exception as e:
        print(f"Error fetching channels: {str(e)}")
        return jsonify({'error': 'Failed to fetch channels'}), 500

@channels_bp.route('', methods=['POST'])
@jwt_required()
def create_channel():
    try:
        current_user_id = get_jwt_identity()
        
        if not is_admin(current_user_id):
            return jsonify({'error': 'Admin access required'}), 403
        
        platform = request.form.get('platform', 'youtube').strip().lower()
        channel_name = request.form.get('channelName', '').strip()
        channel_url = request.form.get('channelUrl', '').strip()
        
        logo_filename = None
        
        if 'logo' in request.files:
            file = request.files['logo']
            if file and file.filename and allowed_file(file.filename):
                os.makedirs(LOGO_FOLDER, exist_ok=True)
                
                original_filename = secure_filename(file.filename)
                file_extension = original_filename.rsplit('.', 1)[1].lower()
                unique_filename = f"{uuid.uuid4()}.{file_extension}"
                file_path = os.path.join(LOGO_FOLDER, unique_filename)
                
                file.save(file_path)
                logo_filename = unique_filename
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO channels (platform, channel_name, channel_logo_path, channel_url, added_at, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id, platform, channel_name, channel_logo_path, channel_url, added_at
            """, (platform, channel_name, logo_filename, channel_url or ''))
            
            new_channel = cursor.fetchone()
            logo_url = f"/api/v1/channels/{new_channel['id']}/logo" if new_channel['channel_logo_path'] else ''
            
            return jsonify({
                'id': new_channel['id'],
                'name': new_channel['channel_name'],
                'logoPath': logo_url,
                'channelLink': new_channel['channel_url'] or '',
                'platform': new_channel.get('platform', 'youtube'),
                'addedAt': new_channel['added_at'].isoformat()
            }), 201
    
    except Exception as e:
        print(f"Error creating channel: {str(e)}")
        return jsonify({'error': 'Failed to create channel'}), 500

@channels_bp.route('/<int:channel_id>', methods=['PUT'])
@jwt_required()
def update_channel(channel_id):
    try:
        current_user_id = get_jwt_identity()
        
        if not is_admin(current_user_id):
            return jsonify({'error': 'Admin access required'}), 403
        
        platform = request.form.get('platform', 'youtube').strip().lower()
        channel_name = request.form.get('channelName', '').strip()
        channel_url = request.form.get('channelUrl', '').strip()
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT channel_logo_path FROM channels WHERE id = %s", (channel_id,))
            existing_channel = cursor.fetchone()
            
            if not existing_channel:
                return jsonify({'error': 'Channel not found'}), 404
            
            logo_filename = existing_channel['channel_logo_path']
            
            if 'logo' in request.files:
                file = request.files['logo']
                if file and file.filename and allowed_file(file.filename):
                    if logo_filename:
                        old_file_path = os.path.join(LOGO_FOLDER, logo_filename)
                        if os.path.exists(old_file_path):
                            try:
                                os.remove(old_file_path)
                            except Exception as e:
                                print(f"Warning: Failed to delete old logo: {str(e)}")
                    
                    os.makedirs(LOGO_FOLDER, exist_ok=True)
                    
                    original_filename = secure_filename(file.filename)
                    file_extension = original_filename.rsplit('.', 1)[1].lower()
                    unique_filename = f"{uuid.uuid4()}.{file_extension}"
                    file_path = os.path.join(LOGO_FOLDER, unique_filename)
                    
                    file.save(file_path)
                    logo_filename = unique_filename
            
            cursor.execute("""
                UPDATE channels
                SET platform = %s, channel_name = %s, channel_logo_path = %s, channel_url = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, platform, channel_name, channel_logo_path, channel_url, added_at
            """, (platform, channel_name, logo_filename, channel_url or '', channel_id))
            
            updated_channel = cursor.fetchone()
            logo_url = f"/api/v1/channels/{updated_channel['id']}/logo" if updated_channel['channel_logo_path'] else ''
            
            return jsonify({
                'id': updated_channel['id'],
                'name': updated_channel['channel_name'],
                'logoPath': logo_url,
                'channelLink': updated_channel['channel_url'] or '',
                'platform': updated_channel.get('platform', 'youtube'),
                'addedAt': updated_channel['added_at'].isoformat()
            }), 200
    
    except Exception as e:
        print(f"Error updating channel: {str(e)}")
        return jsonify({'error': 'Failed to update channel'}), 500

@channels_bp.route('/<int:channel_id>', methods=['DELETE'])
@jwt_required()
def delete_channel(channel_id):
    try:
        current_user_id = get_jwt_identity()
        
        if not is_admin(current_user_id):
            return jsonify({'error': 'Admin access required'}), 403
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("SELECT channel_logo_path FROM channels WHERE id = %s", (channel_id,))
            channel = cursor.fetchone()
            
            if not channel:
                return jsonify({'error': 'Channel not found'}), 404
            
            if channel['channel_logo_path']:
                logo_file_path = os.path.join(LOGO_FOLDER, channel['channel_logo_path'])
                if os.path.exists(logo_file_path):
                    try:
                        os.remove(logo_file_path)
                    except Exception as e:
                        print(f"Warning: Failed to delete logo file: {str(e)}")
            
            cursor.execute("DELETE FROM channels WHERE id = %s", (channel_id,))
            
            return jsonify({'message': 'Channel deleted successfully'}), 200
    
    except Exception as e:
        print(f"Error deleting channel: {str(e)}")
        return jsonify({'error': 'Failed to delete channel'}), 500

@channels_bp.route('/<int:channel_id>/logo', methods=['GET'])
def get_channel_logo(channel_id):
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT channel_logo_path FROM channels WHERE id = %s", (channel_id,))
            channel = cursor.fetchone()
            
            if not channel:
                return jsonify({'error': 'Channel not found'}), 404
            
            if not channel['channel_logo_path']:
                return jsonify({'error': 'Channel has no logo'}), 404
            
            logo_file_path = os.path.join(LOGO_FOLDER, channel['channel_logo_path'])
            
            if not os.path.exists(logo_file_path):
                return jsonify({'error': 'Logo file not found'}), 404
            
            mimetype, _ = mimetypes.guess_type(logo_file_path)
            if not mimetype:
                mimetype = 'application/octet-stream'
            
            return send_file(logo_file_path, mimetype=mimetype)
    
    except Exception as e:
        print(f"Error serving logo: {str(e)}")
        return jsonify({'error': 'Failed to serve logo'}), 500
