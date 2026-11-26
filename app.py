import os
import uuid
from datetime import datetime, date
from functools import wraps
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from openpyxl import Workbook
from io import BytesIO
from config import Config
from database import db, init_database
from models import User, Employee, Project, Travel, Expense, Advance, AuditLog

ALLOWED_RECEIPT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    init_database(app)

    def parse_date(value):
        return datetime.strptime(value, "%Y-%m-%d").date() if value else None

    def parse_money(value):
        try:
            amount = Decimal(str(value or "0"))
            if amount < 0:
                raise ValueError("Amount cannot be negative.")
            return amount
        except (InvalidOperation, ValueError):
            raise ValueError("Enter a valid non-negative amount.")

    def current_user():
        uid = session.get("user_id")
        return db.session.get(User, uid) if uid else None

    def audit(action, entity, entity_id=None, details=""):
        user = current_user()
        db.session.add(AuditLog(username=user.username if user else "system",
                                action=action, entity=entity,
                                entity_id=entity_id, details=details))

    def roles_required(*roles):
        def decorator(func):
            @wraps(func)
            def wrapped(*args, **kwargs):
                user = current_user()
                if not user or not user.active:
                    session.clear()
                    return redirect(url_for("login"))
                if user.role not in roles:
                    flash("You do not have permission for this action.", "danger")
                    return redirect(url_for("dashboard"))
                return func(*args, **kwargs)
            return wrapped
        return decorator

    login_required = roles_required("admin", "manager", "employee")

    @app.context_processor
    def inject_globals():
        return {"today": date.today(), "logged_user": current_user()}

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            user = User.query.filter_by(username=username).first()
            if user and user.active and check_password_hash(user.password_hash, request.form.get("password", "")):
                session.clear()
                session["user_id"] = user.id
                audit("LOGIN", "User", user.id)
                db.session.commit()
                return redirect(url_for("dashboard"))
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard():
        user = current_user()
        expense_query = Expense.query
        travel_query = Travel.query
        advance_query = Advance.query
        if user.role == "employee":
            expense_query = expense_query.filter_by(employee_id=user.employee_id)
            travel_query = travel_query.filter_by(employee_id=user.employee_id)
            advance_query = advance_query.filter_by(employee_id=user.employee_id)
        expenses = expense_query.all()
        projects = Project.query.order_by(Project.name).all()
        total = sum((e.amount or 0) + (e.gst or 0) for e in expenses)
        approved = sum((e.amount or 0) + (e.gst or 0) for e in expenses if e.status in ("Approved", "Reimbursed"))
        pending = sum((e.amount or 0) + (e.gst or 0) for e in expenses if e.status not in ("Approved", "Reimbursed", "Rejected"))
        reimbursed = sum((e.amount or 0) + (e.gst or 0) for e in expenses if e.status == "Reimbursed")
        return render_template("dashboard.html", total=total, approved=approved,
            pending=pending, reimbursed=reimbursed,
            employees=Employee.query.filter_by(active=True).count(),
            travel_count=travel_query.count(),
            advance_total=sum((a.amount or 0) for a in advance_query.all()),
            projects=projects, recent=expense_query.order_by(Expense.id.desc()).limit(8).all())

    @app.route("/employees", methods=["GET", "POST"])
    @roles_required("admin", "manager")
    def employees():
        if request.method == "POST":
            try:
                employee = Employee(code=request.form["code"].strip(), name=request.form["name"].strip(),
                    department=request.form.get("department"), designation=request.form.get("designation"),
                    email=request.form.get("email"), phone=request.form.get("phone"), manager=request.form.get("manager"))
                db.session.add(employee)
                db.session.flush()
                audit("CREATE", "Employee", employee.id, employee.code)
                db.session.commit()
                flash("Employee added.", "success")
            except Exception as exc:
                db.session.rollback()
                flash(f"Could not add employee: {exc}", "danger")
            return redirect(url_for("employees"))
        return render_template("employees.html", employees=Employee.query.order_by(Employee.name).all())

    @app.route("/projects", methods=["GET", "POST"])
    @roles_required("admin", "manager")
    def projects():
        if request.method == "POST":
            try:
                project = Project(code=request.form["code"].strip(), name=request.form["name"].strip(),
                    client=request.form.get("client"), manager=request.form.get("manager"),
                    start_date=parse_date(request.form.get("start_date")),
                    end_date=parse_date(request.form.get("end_date")),
                    budget=parse_money(request.form.get("budget")), status=request.form.get("status", "Active"))
                db.session.add(project)
                db.session.flush()
                audit("CREATE", "Project", project.id, project.code)
                db.session.commit()
                flash("Project added.", "success")
            except Exception as exc:
                db.session.rollback()
                flash(f"Could not add project: {exc}", "danger")
            return redirect(url_for("projects"))
        rows = []
        for project in Project.query.order_by(Project.id.desc()).all():
            actual = sum((e.amount or 0) + (e.gst or 0) for e in Expense.query.filter_by(project_id=project.id).filter(Expense.status != "Rejected").all())
            rows.append((project, actual, max((project.budget or 0) - actual, 0)))
        return render_template("projects.html", rows=rows)

    @app.route("/travel", methods=["GET", "POST"])
    @login_required
    def travel():
        user = current_user()
        if request.method == "POST":
            try:
                employee_id = int(request.form["employee_id"]) if user.role in ("admin", "manager") else user.employee_id
                item = Travel(employee_id=employee_id, project_id=int(request.form["project_id"]),
                    travel_date=parse_date(request.form["travel_date"]), return_date=parse_date(request.form.get("return_date")),
                    origin=request.form.get("origin"), destination=request.form.get("destination"),
                    purpose=request.form.get("purpose"), mode=request.form.get("mode"),
                    hotel=request.form.get("hotel"), advance=parse_money(request.form.get("advance")))
                if not item.travel_date:
                    raise ValueError("Travel date is required.")
                db.session.add(item); db.session.flush()
                audit("CREATE", "Travel", item.id, f"{item.origin} to {item.destination}")
                db.session.commit(); flash("Travel request submitted.", "success")
            except Exception as exc:
                db.session.rollback(); flash(f"Could not submit travel request: {exc}", "danger")
            return redirect(url_for("travel"))
        query = Travel.query.order_by(Travel.id.desc())
        if user.role == "employee":
            query = query.filter_by(employee_id=user.employee_id)
        return render_template("travel.html", travels=query.all(),
            employees=Employee.query.filter_by(active=True).all(),
            projects=Project.query.filter_by(status="Active").all(), u=user)

    @app.route("/advances", methods=["GET", "POST"])
    @login_required
    def advances():
        user = current_user()
        if request.method == "POST":
            try:
                employee_id = int(request.form["employee_id"]) if user.role in ("admin", "manager") else user.employee_id
                item = Advance(advance_no="ADV-" + uuid.uuid4().hex[:8].upper(),
                    employee_id=employee_id, project_id=int(request.form["project_id"]),
                    travel_id=int(request.form["travel_id"]) if request.form.get("travel_id") else None,
                    amount=parse_money(request.form.get("amount")), purpose=request.form.get("purpose"))
                db.session.add(item); db.session.flush()
                audit("CREATE", "Advance", item.id, item.advance_no)
                db.session.commit(); flash("Advance request submitted.", "success")
            except Exception as exc:
                db.session.rollback(); flash(f"Could not submit advance: {exc}", "danger")
            return redirect(url_for("advances"))
        query = Advance.query.order_by(Advance.id.desc())
        if user.role == "employee":
            query = query.filter_by(employee_id=user.employee_id)
        return render_template("advances.html", advances=query.all(),
            employees=Employee.query.filter_by(active=True).all(),
            projects=Project.query.filter_by(status="Active").all(),
            travels=Travel.query.order_by(Travel.id.desc()).all(), u=user)

    @app.route("/expenses", methods=["GET", "POST"])
    @login_required
    def expenses():
        user = current_user()
        if request.method == "POST":
            saved_name = None
            try:
                employee_id = int(request.form["employee_id"]) if user.role in ("admin", "manager") else user.employee_id
                upload = request.files.get("receipt")
                if upload and upload.filename:
                    safe_name = secure_filename(upload.filename)
                    extension = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
                    if extension not in ALLOWED_RECEIPT_EXTENSIONS:
                        raise ValueError("Receipt must be PDF, PNG or JPG.")
                    saved_name = uuid.uuid4().hex + "." + extension
                    upload.save(os.path.join(app.config["UPLOAD_FOLDER"], saved_name))
                expense = Expense(claim_no="CLM-" + uuid.uuid4().hex[:8].upper(),
                    employee_id=employee_id, project_id=int(request.form["project_id"]),
                    travel_id=int(request.form["travel_id"]) if request.form.get("travel_id") else None,
                    expense_date=parse_date(request.form.get("expense_date")),
                    category=request.form["category"], description=request.form.get("description"),
                    amount=parse_money(request.form.get("amount")), gst=parse_money(request.form.get("gst")),
                    payment_method=request.form.get("payment_method"), receipt=saved_name)
                if not expense.expense_date:
                    raise ValueError("Expense date is required.")
                db.session.add(expense); db.session.flush()
                audit("CREATE", "Expense", expense.id, expense.claim_no)
                db.session.commit(); flash("Expense claim submitted.", "success")
            except Exception as exc:
                db.session.rollback()
                if saved_name:
                    try: os.remove(os.path.join(app.config["UPLOAD_FOLDER"], saved_name))
                    except OSError: pass
                flash(f"Could not submit expense: {exc}", "danger")
            return redirect(url_for("expenses"))
        query = Expense.query.order_by(Expense.id.desc())
        if user.role == "employee":
            query = query.filter_by(employee_id=user.employee_id)
        return render_template("expenses.html", expenses=query.all(),
            employees=Employee.query.filter_by(active=True).all(),
            projects=Project.query.filter_by(status="Active").all(),
            travels=Travel.query.order_by(Travel.id.desc()).all(), u=user)

    @app.get("/approvals")
    @roles_required("admin", "manager")
    def approvals():
        return render_template("approvals.html",
            expenses=Expense.query.filter(Expense.status.in_(["Pending Manager", "Pending Finance"])).order_by(Expense.id.desc()).all(),
            travels=Travel.query.filter_by(status="Pending").order_by(Travel.id.desc()).all(),
            advances=Advance.query.filter_by(status="Pending Manager").order_by(Advance.id.desc()).all())

    def update_status(item, status, note="", kind=""):
        item.status = status
        if isinstance(item, Expense):
            if status in ("Rejected", "Approved", "Pending Finance"): item.manager_note = note
            if status == "Reimbursed": item.finance_note = note
        elif hasattr(item, "manager_note"):
            item.manager_note = note
        audit("STATUS", kind or item.__class__.__name__, item.id, f"{status}: {note}")
        db.session.commit()

    @app.post("/expense/<int:item_id>/status/<action>")
    @roles_required("admin", "manager")
    def expense_status(item_id, action):
        item = Expense.query.get_or_404(item_id)
        mapping = {"approve-manager": "Pending Finance", "approve-finance": "Approved",
                   "reject": "Rejected", "reimburse": "Reimbursed"}
        new_status = mapping.get(action)
        if not new_status:
            flash("Invalid action.", "danger")
        elif action in ("approve-finance", "reimburse") and current_user().role != "admin":
            flash("This action is restricted to admin.", "danger")
        else:
            update_status(item, new_status, request.form.get("note", ""), "Expense")
            flash("Expense updated.", "success")
        return redirect(url_for("approvals"))

    @app.post("/travel/<int:item_id>/status/<action>")
    @roles_required("admin", "manager")
    def travel_status(item_id, action):
        item = Travel.query.get_or_404(item_id)
        new_status = {"approve": "Approved", "reject": "Rejected"}.get(action)
        if new_status:
            update_status(item, new_status, request.form.get("note", ""), "Travel")
            flash("Travel updated.", "success")
        else:
            flash("Invalid action.", "danger")
        return redirect(url_for("approvals"))

    @app.post("/advance/<int:item_id>/status/<action>")
    @roles_required("admin", "manager")
    def advance_status(item_id, action):
        item = Advance.query.get_or_404(item_id)
        new_status = {"approve": "Approved", "reject": "Rejected", "pay": "Paid"}.get(action)
        if not new_status:
            flash("Invalid action.", "danger")
        elif action == "pay" and current_user().role != "admin":
            flash("Advance payment is restricted to admin.", "danger")
        else:
            if new_status == "Paid": item.paid_date = date.today()
            update_status(item, new_status, request.form.get("note", ""), "Advance")
            flash("Advance updated.", "success")
        return redirect(url_for("approvals"))

    @app.get("/audit")
    @roles_required("admin")
    def audit_page():
        return render_template("audit.html", logs=AuditLog.query.order_by(AuditLog.id.desc()).limit(300).all())

    @app.get("/uploads/<path:filename>")
    @login_required
    def uploads(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)

    @app.get("/reports/export")
    @login_required
    def export_report():
        user = current_user()
        expense_query, travel_query, advance_query = Expense.query, Travel.query, Advance.query
        if user.role == "employee":
            expense_query = expense_query.filter_by(employee_id=user.employee_id)
            travel_query = travel_query.filter_by(employee_id=user.employee_id)
            advance_query = advance_query.filter_by(employee_id=user.employee_id)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Expenses"
        sheet.append(["Claim No", "Date", "Employee", "Project", "Category", "Description", "Amount", "GST", "Total", "Payment Method", "Status", "Receipt"])
        for e in expense_query.order_by(Expense.expense_date).all():
            sheet.append([e.claim_no, e.expense_date, e.employee.name, e.project.code, e.category,
                          e.description, float(e.amount or 0), float(e.gst or 0),
                          float((e.amount or 0) + (e.gst or 0)), e.payment_method, e.status, e.receipt or ""])
        travel_sheet = workbook.create_sheet("Travel")
        travel_sheet.append(["ID", "Travel Date", "Return Date", "Employee", "Project", "From", "To", "Purpose", "Mode", "Hotel", "Advance", "Status"])
        for t in travel_query.order_by(Travel.travel_date).all():
            travel_sheet.append([t.id, t.travel_date, t.return_date, t.employee.name, t.project.code,
                                 t.origin, t.destination, t.purpose, t.mode, t.hotel, float(t.advance or 0), t.status])
        advance_sheet = workbook.create_sheet("Advances")
        advance_sheet.append(["Advance No", "Request Date", "Employee", "Project", "Amount", "Purpose", "Status", "Paid Date"])
        for a in advance_query.order_by(Advance.request_date).all():
            advance_sheet.append([a.advance_no, a.request_date, a.employee.name, a.project.code,
                                  float(a.amount or 0), a.purpose, a.status, a.paid_date])
        for ws in workbook.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for col in ws.columns:
                width = min(max(max(len(str(cell.value or "")) for cell in col) + 2, 10), 36)
                ws.column_dimensions[col[0].column_letter].width = width
        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return send_file(output, as_attachment=True, download_name="project_expense_mis.xlsx",
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        print("Database tables created.")

    @app.cli.command("create-admin")
    def create_admin():
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            raise RuntimeError("Set ADMIN_PASSWORD before running flask create-admin.")
        if User.query.filter_by(username=username).first():
            print(f"User {username} already exists.")
            return
        db.session.add(User(username=username, password_hash=generate_password_hash(password), role="admin"))
        db.session.commit()
        print(f"Admin user {username} created.")

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
