from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def init_database(app):
    """Attach SQLAlchemy to Flask and create missing tables."""
    db.init_app(app)
    with app.app_context():
        from models import User, Employee, Project, Travel, Expense, Advance, AuditLog
        db.create_all()
