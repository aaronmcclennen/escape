import os
import logging
import uuid
from application.Riddle import Game, Games, Riddle
from flask import Flask
from flask import request
from flask import redirect
from flask import url_for
from flask import render_template
from flask import jsonify
from flask import Blueprint
from flask import session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from application.JsonLoader import ConfigLoader

logging_format = (
    "%(asctime)s - %(levelname)s - %(filename)s - %(funcName)s - %(message)s"
)
logging.basicConfig(level=logging.INFO, format=logging_format)

app = Flask(__name__)
# set secret for session/cookie signing — read from env; fallback only for local dev
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-change-me"))

login_manager = LoginManager(app)
login_manager.login_view = "admin_login"

#load configured question file
config_file = os.getenv("VERMUTEN_CONFIG")
config_loader = ConfigLoader(config_file)
games = Games()
games.add(config_loader.game)

# --- new: admin blueprint and centralized before_request auth ---
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Global in-memory store for user data (not persistent, resets on server restart)
USER_DATA = {}

@app.before_request
def ensure_user_id():
    """Assign a unique user id to each session if not already present."""
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    # Optionally, initialize their data dict if not present
    if session["user_id"] not in USER_DATA:
        USER_DATA[session["user_id"]] = {}

def get_user_store():
    """Get the dict for the current user's server-side data."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return USER_DATA.setdefault(user_id, {})

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
    return redirect((url_for("admin.progress")))


@admin_bp.route("/progress")
def progress():
    return render_template(
        "progress.html.j2",
        current_riddle_number=riddle_manager.get_current_riddle_number(),
        riddle_count=riddle_manager.get_riddle_count(),
        current_riddle=riddle_manager.get_current_riddle().get_riddle(),
        attempts=riddle_manager.get_total_attempt_count(),
    )


@admin_bp.route("/questions", methods=["GET", "POST"])
def admin_questions():
    # prefer the Game object produced by the ConfigLoader
    game = getattr(config_loader, "game", None)
    if game is None:
        game = Game()

    if request.method == "POST":
        new_name = (request.form.get("name") or "").strip()
        if new_name:
            # update the Game used by the page
            game.name = new_name
            # keep the ConfigLoader.game in sync if present
            if getattr(config_loader, "game", None):
                config_loader.game = game
        # PRG: redirect after POST so the page reloads with the updated value
        return redirect(url_for("admin.admin_questions"))

    total_count = game.get_riddle_count()
    return render_template("admin_questions.html.j2", game=game, total_count=total_count)


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
    new_riddle = Riddle(
        payload["question"],
        payload["answer"],
        payload["hint"],
        payload["image_name"],
        [],  # correct_responses
        [],  # incorrect_responses
        "",  # completion_message
        "",  # completion_image_name
    )

    config_loader.game.add_riddle_at_end(new_riddle)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/edit/<int:index>")
def admin_edit_question(index):
    try:
        r = config_loader.game.get_riddle_at_index(index)
    except Exception:
        return redirect(url_for("admin.admin_questions"))
    riddle = {
        "id": index,
        "question": r.get_riddle(),
        "answer": ", ".join(r.answer),
        "hint": r.get_hint(),
        "image_name": r.get_image_name(),
    }
    total_count = config_loader.game.get_riddle_count()
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
    # Create a Riddle object from the payload
    new_riddle = Riddle(
        payload["question"],
        payload["answer"],
        payload["hint"],
        payload["image_name"],
        [],  # correct_responses
        [],  # incorrect_responses
        "",  # completion_message
        "",  # completion_image_name
    )
    config_loader.game.replace_riddle_at_index(index, new_riddle)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/delete/<int:index>", methods=["POST"])
def admin_delete_question(index):
    game = getattr(config_loader, "game", None)
    if game is None:
        game = Game()

    game.remove_riddle_by_index(index)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/move/<int:index>/<direction>", methods=["POST"])
def admin_move_question(index, direction):
    try:
        game = getattr(config_loader, "game", None)
        if game is None:
            game = Game()

        lst = list(game.riddles)
        n = len(lst)
        if index < 0 or index >= n:
            raise Exception("index out of range")
        if direction == "up" and index > 0:
            lst[index - 1], lst[index] = lst[index], lst[index - 1]
        elif direction == "down" and index < n - 1:
            lst[index], lst[index + 1] = lst[index + 1], lst[index]
        else:
            # nothing to do
            return redirect(url_for("admin.admin_questions"))
        # update the Game object and persist via ConfigLoader structures
        game.riddles = lst
    except Exception:
        logging.exception("Failed to move riddle")
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/download")
def admin_download_questions():
    try:
        game_data = config_loader.game.to_json()
        # the riddle json is good #game_data = config_loader.game.get_current_riddle().to_json()
        
        import json
        from flask import make_response
        response = make_response(json.dumps(game_data, indent=2))
        response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Disposition"] = "attachment; filename="+config_loader.game.make_json_filename()
        return response
    except Exception:
        logging.exception("Failed to prepare download")
        return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/")
def admin_index():
    # provide a shallow copy of the sorted games list for the template to iterate
    return render_template("admin_index.html.j2", games=games.get_all())


@admin_bp.route("/upload", methods=["POST"])
def admin_upload():
    file = request.files.get("file")
    if not file:
        return redirect(url_for("admin.admin_index"))
    try:
        # overwrite the configured JSON file with the uploaded file contents
        global config_loader
        target = config_loader.path_to_json_config
        # write bytes to preserve encoding; uploaded file may be binary stream
        with open(target, "wb") as f:
            f.write(file.read())
        # reload config loader
        config_loader = ConfigLoader(target)
        # add the new game to the Games object
        if hasattr(config_loader, "game") and config_loader.game is not None:
            games.add(config_loader.game)
    except Exception:
        logging.exception("Failed to upload new game file")
    return redirect(url_for("admin.admin_questions"))


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
            return redirect(url_for("adminadmin_index"))
        # failed login: re-render with an error flag (or you can flash)
        return redirect(url_for("admin.admin_login", next=next_url, error=1))

    return render_template("admin_login.html.j2")



# register admin blueprint
app.register_blueprint(admin_bp)

if __name__ == "__main__":
    logging.info("Starting vermuten...")
    app.run()
