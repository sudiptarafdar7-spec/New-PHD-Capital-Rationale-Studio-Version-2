from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.api import activity_logs_bp
from backend.models.user import User
from datetime import datetime

def is_admin(user_id):
    user = User.find_by_id(user_id)
    return user and user.get('role') == 'admin'

def create_activity_log(user_id, action, message, job_id=None, tool_used=None):
    """Helper function to create activity log entries"""
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO activity_logs (user_id, job_id, action, tool_used, message, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, job_id, action, tool_used, message, datetime.now()))
            
            result = cursor.fetchone()
            return result['id'] if result else None
    except Exception as e:
        print(f"Error creating activity log: {str(e)}")
        return None

@activity_logs_bp.route('', methods=['GET'])
@jwt_required()
def get_activity_logs():
    try:
        current_user_id = get_jwt_identity()
        
        # Get query parameters for filtering
        tool_filter = request.args.get('tool', 'all')
        user_filter = request.args.get('user', 'all')
        action_filter = request.args.get('action', 'all')
        date_from = request.args.get('dateFrom')
        date_to = request.args.get('dateTo')
        search_query = request.args.get('search', '')
        
        with get_db_cursor() as cursor:
            query = """
                SELECT 
                    al.id,
                    al.user_id,
                    al.job_id,
                    al.action,
                    al.tool_used,
                    al.message,
                    al.timestamp,
                    u.first_name,
                    u.last_name,
                    u.avatar_path
                FROM activity_logs al
                LEFT JOIN users u ON al.user_id = u.id
                WHERE 1=1
            """
            params = []
            
            if tool_filter != 'all' and tool_filter != 'none':
                query += " AND al.tool_used = %s"
                params.append(tool_filter)
            elif tool_filter == 'none':
                query += " AND al.tool_used IS NULL"
            
            if user_filter != 'all':
                query += " AND al.user_id = %s"
                params.append(user_filter)
            
            if action_filter != 'all':
                query += " AND al.action = %s"
                params.append(action_filter)
            
            if date_from:
                query += " AND al.timestamp >= %s"
                params.append(date_from)
            
            if date_to:
                query += " AND al.timestamp <= %s::date + interval '1 day'"
                params.append(date_to)
            
            if search_query:
                query += " AND (al.message ILIKE %s OR al.job_id ILIKE %s)"
                search_param = f"%{search_query}%"
                params.extend([search_param, search_param])
            
            query += " ORDER BY al.timestamp DESC LIMIT 100"
            
            cursor.execute(query, tuple(params))
            logs = cursor.fetchall()
            
            return jsonify({
                'success': True,
                'logs': logs
            }), 200
            
    except Exception as e:
        print(f"Error fetching activity logs: {str(e)}")
        return jsonify({'error': 'Failed to fetch activity logs'}), 500

@activity_logs_bp.route('', methods=['POST'])
@jwt_required()
def create_log():
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        action = data.get('action')
        message = data.get('message')
        job_id = data.get('jobId')
        tool_used = data.get('toolUsed')
        
        if not action or not message:
            return jsonify({'error': 'Action and message are required'}), 400
        
        log_id = create_activity_log(current_user_id, action, message, job_id, tool_used)
        
        if log_id:
            return jsonify({
                'success': True,
                'logId': log_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create activity log'}), 500
            
    except Exception as e:
        print(f"Error creating activity log: {str(e)}")
        return jsonify({'error': 'Failed to create activity log'}), 500
