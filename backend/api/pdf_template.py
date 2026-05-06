from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from backend.utils.database import get_db_cursor
from backend.api import pdf_template_bp
from datetime import datetime

def get_current_user():
    user_id = get_jwt_identity()
    with get_db_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        return user

def format_pdf_template(row):
    return {
        'id': row['id'],
        'company_name': row['company_name'] or '',
        'registration_details': row['registration_details'] or '',
        'disclaimer_text': row['disclaimer_text'] or '',
        'disclosure_text': row['disclosure_text'] or '',
        'company_data': row['company_data'] or '',
        'updated_at': row['updated_at'].isoformat() if row['updated_at'] else None,
    }

@pdf_template_bp.route('', methods=['GET'])
@jwt_required()
def get_pdf_template():
    """Get PDF template (single row)"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        with get_db_cursor() as cursor:
            cursor.execute("SELECT * FROM pdf_template ORDER BY id LIMIT 1")
            template = cursor.fetchone()
            
            if template:
                return jsonify(format_pdf_template(template)), 200
            else:
                # Return empty template if none exists
                return jsonify({
                    'company_name': '',
                    'registration_details': '',
                    'disclaimer_text': '',
                    'disclosure_text': '',
                    'company_data': '',
                }), 200
                
    except Exception as e:
        print(f"Error getting PDF template: {e}")
        return jsonify({'error': str(e)}), 500

@pdf_template_bp.route('', methods=['PUT'])
@jwt_required()
def update_pdf_template():
    """Update PDF template (single row)"""
    try:
        current_user = get_current_user()
        if not current_user or current_user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        data = request.get_json()
        company_name = data.get('company_name', '')
        registration_details = data.get('registration_details', '')
        disclaimer_text = data.get('disclaimer_text', '')
        disclosure_text = data.get('disclosure_text', '')
        company_data = data.get('company_data', '')
        
        with get_db_cursor(commit=True) as cursor:
            # Check if template exists
            cursor.execute("SELECT id FROM pdf_template ORDER BY id LIMIT 1")
            existing = cursor.fetchone()
            
            if existing:
                # Update existing template
                cursor.execute("""
                    UPDATE pdf_template 
                    SET company_name = %s,
                        registration_details = %s,
                        disclaimer_text = %s,
                        disclosure_text = %s,
                        company_data = %s,
                        updated_at = %s
                    WHERE id = %s
                    RETURNING *
                """, (company_name, registration_details, disclaimer_text, disclosure_text, company_data, datetime.now(), existing['id']))
            else:
                # Create new template
                cursor.execute("""
                    INSERT INTO pdf_template (company_name, registration_details, disclaimer_text, disclosure_text, company_data, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                """, (company_name, registration_details, disclaimer_text, disclosure_text, company_data, datetime.now()))
            
            updated_template = cursor.fetchone()
            return jsonify(format_pdf_template(updated_template)), 200
            
    except Exception as e:
        print(f"Error updating PDF template: {e}")
        return jsonify({'error': str(e)}), 500
