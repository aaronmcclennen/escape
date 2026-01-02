import os
import logging
from flask import Flask
from flask import request
from flask import redirect
from flask import url_for
from flask import render_template
from flask import jsonify
from flask import Blueprint
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from application.JsonLoader import ConfigLoader

logging_format = (
    "%(asctime)s - %(levelname)s - %(filename)s - %(funcName)s - %(message)s"
)
logging.basicConfig(level=logging.INFO, format=logging_format)

app = Flask(__name__)
config_file = os.getenv("VERMUTEN_CONFIG")
config_loader = ConfigLoader(config_file)
riddle_manager = config_loader.get_riddle_manager()

login_manager = LoginManager(app)
login_manager.login_view = "admin_login"

# --- new: admin blueprint and centralized before_request auth ---
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

@admin_bp.before_request
def require_admin_login():
    # allow static files and the login endpoint through
    if request.endpoint == 'static':
        return None
    # admin_login is defined as an app route (see below) and must remain accessible
    if request.endpoint == 'admin_login':
        return None
    # if already logged in allow
    if current_user.is_authenticated:
        return None
    # otherwise redirect to login (preserve next)
    return redirect(url_for("admin_login", next=request.path))

# trivial single-user backed by env var
class AdminUser(UserMixin):
    id = "admin"

@login_manager.user_loader
def load_user(user_id):
    if user_id == "admin":
        return AdminUser()
    return None

@app.route("/")
def riddle():
    guess = request.args.get("guess")
    current_riddle = riddle_manager.get_current_riddle()
    riddle_id = riddle_manager.get_current_riddle_number()
    if guess is None and current_riddle is not None:
        return render_template(
            "index.html.j2",
            riddle_id=riddle_id,
            riddle=current_riddle.get_riddle(),
            image_name=current_riddle.get_image_name(),
            hint=current_riddle.get_hint(),
        )
    elif guess is not None and current_riddle is not None:
        if current_riddle.test_answer(guess):
            riddle_manager.next_riddle()
            return redirect(url_for("riddle"))
        else:
            return render_template(
                "index.html.j2",
                riddle_id=riddle_id,
                riddle=current_riddle.get_riddle(),
                image_name=current_riddle.get_image_name(),
                hint=current_riddle.get_hint(),
                response=current_riddle.get_random_incorrect_response(),
            )
    else:
        logging.info(riddle_manager.get_current_riddle())
        return render_template(
            "complete.html.j2",
            completion_message=riddle_manager.get_completion_message(),
            image_name=riddle_manager.get_completion_image_name(),
            attempts=riddle_manager.get_total_attempt_count(),
        )


@app.route("/data")
def api_data():
    current_riddle = riddle_manager.get_current_riddle()
    if current_riddle is None:
        game_over = True
        return jsonify(game_over=game_over)
    else:
        riddle = current_riddle.get_riddle()
        image_name = current_riddle.get_image_name()
        riddle_id = riddle_manager.get_current_riddle_number()
        hint = current_riddle.get_hint()
        return jsonify(
            riddle_id=f"Riddle #{riddle_id}",
            riddle=riddle,
            image_name=f"./static/{image_name}",
            hint=f"Hint: {hint}",
        )


@app.route("/restart")
def reset():
    current_riddle = riddle_manager.get_current_riddle()
    if current_riddle is None:
        riddle_manager.reset_progress()
    return redirect(url_for("riddle"))


@admin_bp.route("/reset")
def reset_admin_page():
    riddle_manager.reset_progress()
    return redirect((url_for("progress")))


@admin_bp.route("/progress")
def progress():
    return render_template(
        "progress.html.j2",
        current_riddle_number=riddle_manager.get_current_riddle_number(),
        riddle_count=riddle_manager.get_riddle_count(),
        current_riddle=riddle_manager.get_current_riddle().get_riddle(),
        attempts=riddle_manager.get_total_attempt_count(),
    )


@admin_bp.route("/questions")
def admin_questions():
    # list riddles
    riddles = []
    for i in range(len(config_loader.get_riddles())):
        r = config_loader.get_riddles()[i]
        riddles.append({"id": i, "question": r.get_riddle(), "answer": r.answer, "hint": r.get_hint(), "image_name": r.get_image_name()})
    total_count = len(config_loader.get_riddles())
    return render_template("admin_questions.html.j2", riddles=riddles, total_count=total_count)


@admin_bp.route("/questions/new")
def admin_new_question():
    return render_template("admin_edit.html.j2", action="create", riddle=None)


@admin_bp.route("/questions/create", methods=["POST"])
def admin_create_question():
    payload = {
        "question": request.form.get("question", ""),
        "answer": [
            s.strip() for s in request.form.get("answer", "").split(",") if s.strip()
        ],
        "hint": request.form.get("hint", ""),
        "image_name": request.form.get("image_name", ""),
    }
    config_loader.add_riddle(payload)
    # sync in-memory manager
    riddle_manager.riddles = config_loader.get_riddles()
    return redirect(url_for("admin_questions"))


@admin_bp.route("/questions/edit/<int:index>")
def admin_edit_question(index):
    try:
        r = config_loader.get_riddles()[index]
    except Exception:
        return redirect(url_for("admin_questions"))
    riddle = {
        "id": index,
        "question": r.get_riddle(),
        "answer": ", ".join(r.answer),
        "hint": r.get_hint(),
        "image_name": r.get_image_name(),
    }
    total_count = len(config_loader.get_riddles())
    return render_template("admin_edit.html.j2", action="update", riddle=riddle, total_count=total_count)


@admin_bp.route("/questions/update/<int:index>", methods=["POST"])
def admin_update_question(index):
    payload = {
        "question": request.form.get("question", ""),
        "answer": [
            s.strip() for s in request.form.get("answer", "").split(",") if s.strip()
        ],
        "hint": request.form.get("hint", ""),
        "image_name": request.form.get("image_name", ""),
    }
    config_loader.update_riddle(index, payload)
    riddle_manager.riddles = config_loader.get_riddles()
    return redirect(url_for("admin_questions"))


@admin_bp.route("/questions/delete/<int:index>", methods=["POST"])
def admin_delete_question(index):
    config_loader.delete_riddle(index)
    riddle_manager.riddles = config_loader.get_riddles()
    # ensure current index not out of range
    if (
        riddle_manager.get_current_riddle() is None
        and riddle_manager.get_current_riddle_number() > riddle_manager.get_riddle_count()
    ):
        riddle_manager.reset_progress()
    return redirect(url_for("admin_questions"))


@admin_bp.route("/questions/move/<int:index>/<direction>", methods=["POST"])
def admin_move_question(index, direction):
    try:
        rc = config_loader.get_riddles()
        n = len(rc)
        if index < 0 or index >= n:
            raise Exception("index out of range")
        # make ordered list
        lst = [rc[i] for i in range(n)]
        if direction == "up" and index > 0:
            lst[index - 1], lst[index] = lst[index], lst[index - 1]
        elif direction == "down" and index < n - 1:
            lst[index], lst[index + 1] = lst[index + 1], lst[index]
        else:
            # nothing to do
            return redirect(url_for("admin_questions"))
        # rebuild dict with 0..n-1 keys and persist
        new = {i: r for i, r in enumerate(lst)}
        config_loader.riddle_collection = new
        config_loader.save_config()
        riddle_manager.riddles = config_loader.get_riddles()
    except Exception:
        logging.exception("Failed to move riddle")
    return redirect(url_for("admin_questions"))


@admin_bp.route("/questions/download")
def admin_download_questions():
    try:
        rc = config_loader.get_riddles()
        riddles = []
        for i in range(len(rc)):
            r = rc[i]
            riddles.append({
                "question": r.get_riddle(),
                "answer": r.answer,
                "hint": r.get_hint(),
                "image_name": r.get_image_name(),
            })
        import json
        from flask import make_response
        response = make_response(json.dumps({"riddles": riddles}, indent=2))
        response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Disposition"] = "attachment; filename=riddles.json"
        return response
    except Exception:
        logging.exception("Failed to prepare download")
        return redirect(url_for("admin_questions"))


@admin_bp.route("/")
def admin_index():
    return render_template("admin_index.html.j2")


@admin_bp.route("/upload", methods=["POST"])
def admin_upload():
    file = request.files.get("file")
    if not file:
        return redirect(url_for("admin_index"))
    try:
        # overwrite the configured JSON file with the uploaded file contents
        global config_loader, riddle_manager
        target = config_loader.path_to_json_config
        # write bytes to preserve encoding; uploaded file may be binary stream
        with open(target, "wb") as f:
            f.write(file.read())
        # reload config loader and riddle manager
        config_loader = ConfigLoader(target)
        riddle_manager = config_loader.get_riddle_manager()
    except Exception:
        logging.exception("Failed to upload new game file")
    return redirect(url_for("admin_questions"))


@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    # preserve next param from query (GET) or form (POST)
    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        user = request.form.get("user", "")
        pw = request.form.get("password", "")
        admin_user = os.getenv("ADMIN_USER")
        admin_pass_hash = os.getenv("ADMIN_PASS_HASH")
        # require both env vars to be set and validate hash
        if admin_user and admin_pass_hash and user == admin_user and check_password_hash(admin_pass_hash, pw):
            login_user(AdminUser())
            # only redirect to a safe relative path
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("admin_index"))
        # failed login: re-render with an error flag (or you can flash)
        return redirect(url_for("admin_login", next=next_url, error=1))

    return render_template("admin_login.html.j2")


# register admin blueprint
app.register_blueprint(admin_bp)

if __name__ == "__main__":
    logging.info("Starting vermuten...")
    app.run()
