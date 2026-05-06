import uuid
import bcrypt
from datetime import datetime
from backend.utils.database import get_db_cursor

class User:
    @staticmethod
    def generate_id():
        return f"user-{uuid.uuid4().hex[:8]}"
    
    @staticmethod
    def hash_password(password):
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    @staticmethod
    def verify_password(password, password_hash):
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    
    @staticmethod
    def create(first_name, last_name, email, mobile, role, password, avatar_path=None):
        user_id = User.generate_id()
        password_hash = User.hash_password(password)
        now = datetime.utcnow().isoformat()
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO users (id, first_name, last_name, email, mobile, role, password_hash, avatar_path, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, first_name, last_name, email, mobile, role, avatar_path, created_at, updated_at
            """, (user_id, first_name, last_name, email, mobile, role, password_hash, avatar_path, now, now))
            
            user = cursor.fetchone()
            return dict(user)
    
    @staticmethod
    def find_by_email(email):
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, first_name, last_name, email, mobile, role, password_hash, avatar_path, created_at, updated_at
                FROM users WHERE email = %s
            """, (email,))
            
            user = cursor.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def find_by_id(user_id):
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, first_name, last_name, email, mobile, role, avatar_path, created_at, updated_at
                FROM users WHERE id = %s
            """, (user_id,))
            
            user = cursor.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def get_all():
        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id, first_name, last_name, email, mobile, role, avatar_path, created_at, updated_at
                FROM users ORDER BY created_at DESC
            """)
            
            users = cursor.fetchall()
            return [dict(user) for user in users]
    
    @staticmethod
    def update(user_id, **kwargs):
        allowed_fields = ['first_name', 'last_name', 'email', 'mobile', 'role', 'avatar_path', 'password']
        updates = []
        values = []
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                if field == 'password':
                    updates.append("password_hash = %s")
                    values.append(User.hash_password(value))
                else:
                    updates.append(f"{field} = %s")
                    values.append(value)
        
        if not updates:
            return User.find_by_id(user_id)
        
        updates.append("updated_at = %s")
        values.append(datetime.utcnow().isoformat())
        values.append(user_id)
        
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = %s RETURNING id, first_name, last_name, email, mobile, role, avatar_path, created_at, updated_at"
        
        with get_db_cursor(commit=True) as cursor:
            cursor.execute(query, values)
            user = cursor.fetchone()
            return dict(user) if user else None
    
    @staticmethod
    def delete(user_id):
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            result = cursor.fetchone()
            return bool(result)
