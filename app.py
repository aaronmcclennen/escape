import os
import logging
from flask import Flask
from flask import request
from flask import redirect
from flask import url_for
from flask import render_template
from flask import jsonify
from application.JsonLoader import ConfigLoader
from functools import wraps
from flask import session, redirect, url_for, request
from authlib.integrations.flask_client import OAuth

logging_format = (
    "%(asctime)s - %(levelname)s - %(filename)s - %(funcName)s - %(message)s"
)
logging.basicConfig(level=logging.INFO, format=logging_format)

app = Flask(__name__)
config_file = os.getenv("VERMUTEN_CONFIG")
config_loader = ConfigLoader(config_file)
riddle_manager = config_loader.get_riddle_manager()


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


@app.route("/admin/reset")
def reset_admin_page():
    riddle_manager.reset_progress()
    return redirect((url_for("progress")))


@app.route("/admin/progress")
def progress():
    return render_template(
        "progress.html.j2",
        current_riddle_number=riddle_manager.get_current_riddle_number(),
        riddle_count=riddle_manager.get_riddle_count(),
        current_riddle=riddle_manager.get_current_riddle().get_riddle(),
        attempts=riddle_manager.get_total_attempt_count(),
    )


@app.route("/admin/questions")
def admin_questions():
    # list riddles
    riddles = []
    for i in range(len(config_loader.get_riddles())):
        r = config_loader.get_riddles()[i]
        riddles.append({"id": i, "question": r.get_riddle(), "answer": r.answer, "hint": r.get_hint(), "image_name": r.get_image_name()})
    total_count = len(config_loader.get_riddles())
    return render_template("admin_questions.html.j2", riddles=riddles, total_count=total_count)


@app.route("/admin/questions/new")
def admin_new_question():
    return render_template("admin_edit.html.j2", action="create", riddle=None)


@app.route("/admin/questions/create", methods=["POST"])
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


@app.route("/admin/questions/edit/<int:index>")
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


@app.route("/admin/questions/update/<int:index>", methods=["POST"])
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


@app.route("/admin/questions/delete/<int:index>", methods=["POST"])
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


@app.route("/admin/questions/move/<int:index>/<direction>", methods=["POST"])
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


@app.route("/admin/questions/download")
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


@app.route("/admin")
def admin_index():
    return render_template("admin_index.html.j2")

@app.route("/admin/upload", methods=["POST"])
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


# --- OAuth setup (Authlib) ---
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret"))
oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

def is_allowed_email(email: str) -> bool:
    allowed_list = os.getenv("ADMIN_GOOGLE_EMAILS", "")  # comma-separated emails
    allowed_domain = os.getenv("ADMIN_GOOGLE_DOMAIN", "")  # single domain, e.g. example.com
    if not email:
        return False
    if allowed_list:
        emails = [e.strip().lower() for e in allowed_list.split(",") if e.strip()]
        if email.lower() in emails:
            return True
    if allowed_domain:
        return email.lower().endswith("@" + allowed_domain.lower())
    return False

def require_admin(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("admin_email"):
            return f(*args, **kwargs)
        # redirect to login, preserve next
        return redirect(url_for("login", next=request.path))
    return wrapped

def _is_public_admin_endpoint(path: str) -> bool:
    # allow root, login callback, login page, logout, and static assets
    if path == "/":
        return True
    if path.startswith("/static"):
        return True
    if path in ("/login", "/auth", "/logout"):
        return True
    return False

@app.before_request
def protect_admin_paths():
    # Protect all /admin* URLs unless the user is already authenticated
    p = request.path or ""
    if p.startswith("/admin"):
        if session.get("admin_email"):
            return None  # allowed
        if _is_public_admin_endpoint(p):
            return None
        # redirect to OAuth login, preserve next
        return redirect(url_for("login", next=p))

# --- Login / callback routes ---
@app.route("/login")
def login():
    redirect_uri = url_for("auth", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route("/auth")
def auth():
    token = oauth.google.authorize_access_token()
    # parse id token to get verified email
    userinfo = oauth.google.parse_id_token(token)
    email = userinfo.get("email")
    email_verified = userinfo.get("email_verified", False)
    if not (email and email_verified and is_allowed_email(email)):
        return "Forbidden", 403
    # mark session as admin
    session["admin_email"] = email
    next_url = request.args.get("next") or url_for("admin_index")
    return redirect(next_url)

@app.route("/logout")
def logout():
    session.pop("admin_email", None)
    return redirect(url_for("index"))  # change as appropriate

if __name__ == "__main__":
    logging.info("Starting vermuten...")
    app.run()
