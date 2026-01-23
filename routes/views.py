from flask import Blueprint, render_template

views_bp = Blueprint("views", __name__)

@views_bp.route("/")
def dashboard():
    return render_template("dashboard.html", active_page='dashboard')

@views_bp.route("/login")
def login():
    return render_template("login.html")

@views_bp.route("/views/artifacts")
def artifacts():
    return render_template("artifacts.html", active_page='artifacts')

@views_bp.route("/views/files")
def files():
    return render_template("files.html", active_page='files')

@views_bp.route("/views/devices")
def devices():
    return render_template("devices.html", active_page='devices')

@views_bp.route("/views/admin")
def admin():
    return render_template("admin.html", active_page='admin')
