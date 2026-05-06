from backend.utils.database import init_database
from backend.models.user import User

def seed_users():
    print("\n=== Seeding Database ===\n")
    
    print("1. Initializing database tables...")
    init_database()
    
    print("\n2. Creating admin user...")
    try:
        admin = User.create(
            first_name='Admin',
            last_name='User',
            email='admin@phdcapital.in',
            mobile='+91 98765 43210',
            role='admin',
            password='admin123',
            avatar_path='https://api.dicebear.com/7.x/avataaars/svg?seed=Admin'
        )
        print(f"   ✓ Admin created: {admin['email']}")
    except Exception as e:
        print(f"   ℹ Admin already exists or error: {e}")
    
    print("\n3. Creating employee user...")
    try:
        employee = User.create(
            first_name='Rajesh',
            last_name='Kumar',
            email='rajesh@phdcapital.in',
            mobile='+91 98765 43211',
            role='employee',
            password='employee123',
            avatar_path='https://api.dicebear.com/7.x/avataaars/svg?seed=Rajesh'
        )
        print(f"   ✓ Employee created: {employee['email']}")
    except Exception as e:
        print(f"   ℹ Employee already exists or error: {e}")
    
    print("\n=== Database seeding complete! ===\n")
    print("Login credentials:")
    print("  Admin:    admin@phdcapital.in / admin123")
    print("  Employee: rajesh@phdcapital.in / employee123\n")

if __name__ == '__main__':
    seed_users()
