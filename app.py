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
from flask import flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from application.JsonLoader import ConfigLoader
import secrets  # new import near the other imports
from datetime import datetime, timezone, timedelta

logging_format = (
    "%(asctime)s - %(levelname)s - %(filename)s - %(funcName)s - %(message)s"
)
logging.basicConfig(level=logging.INFO, format=logging_format)

# list of bird names used for display names
BIRD_NAMES = [
    "Sparrow", "Finch", "Robin", "Bluejay", "Cardinal", "Wren", "Warbler",
    "Lark", "Oriole", "Nightingale", "Pipit", "Swallow", "Swift", "Kingfisher",
    "Heron", "Egret", "Gull", "Tern", "Plover", "Sandpiper", "Albatross",
    "Falcon", "Kestrel", "Hawk", "Eagle", "Crow", "Raven", "Magpie", "Pelican", "Dove"
]

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

def get_selected_game():
    user_store = get_user_store()
    return user_store.get("selected_game", None)

def get_active_game():
    """Return the in-progress/staged game for the current admin, separate from the editing selection."""
    user_store = get_user_store()
    return user_store.get("active_game", None) if user_store else None

def select_game_from_form():
    """
    Read game_id from the request (GET or POST) and return (selected_game, game_id).
    Falls back to the first game or an empty Game if none available.
    """
    game_id = request.args.get("game_id") or request.form.get("game_id")
    selected_game = None

    if game_id:
        # try Games.find first, then fall back to matching name or filename
        selected_game = games.find(game_id)
        if not selected_game:
            for g in games.get_all():
                if getattr(g, "name", None) == game_id or getattr(g, "filename", None) == game_id:
                    selected_game = g
                    break

    if not selected_game:
        selected_game = games.get_all()[0] if games.get_all() else Game("Untitled", [])
        logging.info(f"Falling back to first game: {selected_game.name}. didn't find {game_id} ")

    return selected_game, game_id

# --- new: admin blueprint and centralized before_request auth ---
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Global in-memory store for user data (not persistent, resets on server restart)
USER_DATA = {}

@app.before_request
def ensure_user_id():
    """Assign a unique user id to each session and a bird display name on first visit."""
    if "user_id" not in session:
        session["user_id"] = str(uuid.uuid4())
    user_id = session["user_id"]
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {}
    # assign a bird display name if not already present
    store = USER_DATA[user_id]
    if "display_name" not in store:
        used = {s.get("display_name") for s in USER_DATA.values() if s.get("display_name")}
        available = [b for b in BIRD_NAMES if b not in used]
        if available:
            store["display_name"] = secrets.choice(available)
        else:
            # fallback: reuse a bird with a short unique suffix
            store["display_name"] = f"{secrets.choice(BIRD_NAMES)}-{user_id[:6]}"

def get_user_store():
    """Get the dict for the current user's server-side data."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    return USER_DATA.setdefault(user_id, {})

def get_user_name():
    store = get_user_store()
    return store.get("display_name") if store else None

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
def index():
    """
    Show a list of staged or in-progress games on the index page.
    """
    staged_or_active = []
    for g in games.get_all():
        if g.is_in_progress():
            staged_or_active.append(g)

    return render_template("index_games.html.j2", games=staged_or_active, user_name=get_user_name())


@app.route("/join", methods=["GET", "POST"])
def join_game():
    """
    Join a staged or in-progress game. Requires `game_id` and `entry_code`.
    Stores the selected game in the user's server-side store only after code validation.
    """
    game_id = request.args.get("game_id") or request.form.get("game_id")
    entry_code = request.args.get("entry_code") or request.form.get("entry_code")

    if not game_id:
        flash("No game selected.", "error")
        return redirect(url_for("index"))

    # find selected game by id/name/filename
    selected_game = games.find(game_id)
    if not selected_game:
        for g in games.get_all():
            if getattr(g, "name", None) == game_id or getattr(g, "filename", None) == game_id:
                selected_game = g
                break

    if not selected_game:
        flash("Selected game not found.", "error")
        return redirect(url_for("index"))

    if selected_game.state not in (selected_game.STATE_STAGED, selected_game.STATE_IN_PROGRESS):
        flash(f"Cannot join — the game '{selected_game.name}' is not active.", "error")
        return redirect(url_for("index"))

    # Require entry code
    if not entry_code:
        flash("Game code required to join.", "error")
        return redirect(url_for("index"))

    expected_code = selected_game.get_entry_code()
    if expected_code is None or entry_code != expected_code:
        flash("Invalid game code.", "error")
        return redirect(url_for("index"))

    user_store = get_user_store()
    if user_store is None:
        flash("Session error.", "error")
        return redirect(url_for("index"))

    # store selected game in user store
    user_store["selected_game"] = selected_game
    flash(f"Joined game: {selected_game.name}", "info")

    # If the game is staged, send the user to a waiting page until it becomes in_progress.
    if selected_game.state == selected_game.STATE_STAGED:
        return redirect(url_for("wait"))

    # If already in progress, go to riddle page
    return redirect(url_for("riddle"))


@app.route("/wait")
def wait():
    """
    Waiting page for users who joined a staged game.
    The page polls `/wait_status` and will redirect to `/riddle` when the game becomes in_progress.
    """
    user_store = get_user_store()
    selected_game = user_store.get("selected_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("index"))

    # If the game already moved to in_progress, redirect immediately
    if selected_game.state == selected_game.STATE_IN_PROGRESS:
        return redirect(url_for("riddle"))

    return render_template("wait.html.j2", game=selected_game, user_name=get_user_name())


@app.route("/wait_status")
def wait_status():
    """
    Return JSON with the current state of the user's selected game.
    The wait page polls this endpoint to know when to redirect clients to /riddle.
    """
    user_store = get_user_store()
    selected_game = user_store.get("selected_game") if user_store else None

    if not selected_game:
        return jsonify({"error": "no_selected_game"}), 400

    return jsonify({"state": selected_game.state})


@app.route("/riddle", methods=["GET", "POST"])
def riddle():
    user_store = get_user_store()
    selected_game = user_store.get("selected_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("index"))

    guess = request.args.get("guess") or request.form.get("guess")

    try:
        current_riddle = selected_game.get_riddle_at_index(selected_game.current_riddle_index)
    except Exception:
        current_riddle = None

    # if there is no current riddle -> game complete; send users to results page
    if current_riddle is None:
        return redirect(url_for("results"))

    if not guess:
        return render_template(
            "user_game.html.j2",
            title=selected_game.name,
            riddle_id=selected_game.get_current_riddle_number(),
            riddle=current_riddle.get_riddle(),
            image_name=current_riddle.get_image_name(),
            hint=current_riddle.get_hint(),
            advance=False,
            response=None,
            user_name=get_user_name(),
        )

    try:
        if current_riddle.test_answer(guess):
            # increment per-user correct count
            uid = session.get("user_id")
            if uid:
                selected_game.user_scores[uid] = selected_game.user_scores.get(uid, 0) + 1
            selected_game.next_riddle()
            return redirect(url_for("riddle"))
        else:
            logging.info("Bad guess. Wanted %s got %s", current_riddle.answer, guess)
            try:
                response = current_riddle.get_random_incorrect_response()
            except Exception:
                response = "Incorrect."
            return render_template(
                "user_game.html.j2",
                title=selected_game.name,
                riddle_id=selected_game.get_current_riddle_number(),
                riddle=current_riddle.get_riddle(),
                image_name=current_riddle.get_image_name(),
                hint=current_riddle.get_hint(),
                response=response,
                advance=False,
                user_name=get_user_name(),
            )
    except Exception:
        logging.exception("Error while evaluating guess")
        flash("Error processing your guess.", "error")
        return redirect(url_for("riddle"))

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


@admin_bp.route("/questions", methods=["GET", "POST"])
def admin_questions():
    # Get the user's data store
    user_store = get_user_store()

    # If admin requested creation of a new empty game via POST, create and select it.
    if request.method == "POST" and request.form.get("create_new"):
        new_name = (request.form.get("new_game_name") or "New Game").strip()
        new_game = Game(new_name, [])
        games.add(new_game)
        # store and mark editing for this admin
        user_store["selected_game"] = new_game
        try:
            new_game.mark_editing()
        except Exception:
            logging.exception("Failed to mark new game editing")
        # redirect to questions page for the new game
        return redirect(url_for("admin.admin_questions", game_id=new_game.name))

    # Determine selected game (by index or id, for example via ?game_id= or a form field)
    selected_game, game_id = select_game_from_form()

    # Deny edit if another admin is already editing this game
    # allow if the current user already has this game selected
    current_user_selected = user_store.get("selected_game")
    if selected_game.state == selected_game.STATE_EDITING and current_user_selected is not selected_game:
        logging.info("admin_questions: denying edit, game %s already in STATE_EDITING", selected_game.name)
        flash(f"Cannot edit — the game '{selected_game.name}' is currently being edited by another admin. Please try again later.", "error")
        return redirect(url_for("admin.admin_index"))

    if selected_game.is_in_progress():
        logging.info("admin_questions: denying edit, game %s in progress (state=%s)", selected_game.name, selected_game.state)
        flash(f"Cannot edit — the game '{selected_game.name}' is in state '{selected_game.state}'. Only games in state 'ready' may be edited.", "error")
        return redirect(url_for("admin.admin_index"))

    # Store the selected game in the user's server-side data store
    user_store["selected_game"] = selected_game
    selected_game.mark_editing()

    # Handle POST to update game name (existing behavior)
    if request.method == "POST" and request.form.get("name"):
        new_name = (request.form.get("name") or "").strip()
        if new_name:
            selected_game.name = new_name
        # PRG: redirect after POST so the page reloads with the updated value
        return redirect(url_for("admin.admin_questions", game_id=selected_game.name))

    total_count = selected_game.get_riddle_count()
    return render_template("admin_questions.html.j2", game=selected_game, total_count=total_count)


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

    get_selected_game().add_riddle_at_end(new_riddle)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/edit/<int:index>")
def admin_edit_question(index):
    try:
        r = get_selected_game().get_riddle_at_index(index)
    except Exception:
        return redirect(url_for("admin.admin_questions"))
    riddle = {
        "id": index,
        "question": r.get_riddle(),
        "answer": ", ".join(r.answer),
        "hint": r.get_hint(),
        "image_name": r.get_image_name(),
    }
    total_count = get_selected_game().get_riddle_count()
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
    get_selected_game().replace_riddle_at_index(index, new_riddle)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/delete/<int:index>", methods=["POST"])
def admin_delete_question(index):
    game = get_selected_game()

    game.remove_riddle_by_index(index)
    return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/questions/move/<int:index>/<direction>", methods=["POST"])
def admin_move_question(index, direction):
    try:
        game = get_selected_game()

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
        game_data = get_selected_game().to_json()
        # the riddle json is good #game_data = get_selected_game().get_current_riddle().to_json()
        
        import json
        from flask import make_response
        response = make_response(json.dumps(game_data, indent=2))
        response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Disposition"] = "attachment; filename="+get_selected_game().make_json_filename()
        return response
    except Exception:
        logging.exception("Failed to prepare download")
        return redirect(url_for("admin.admin_questions"))


@admin_bp.route("/")
def admin_index():
    selected_game = get_selected_game()
    logging.info("Selected game: %s", selected_game)
    if selected_game is not None:
        try:
            # Do not force a READY state if the game is STAGED or IN_PROGRESS
            if not selected_game.is_in_progress():
                selected_game.mark_ready()
        except Exception:
            logging.exception("admin_index: failed to update selected game state")
    # provide a shallow copy of the sorted games list for the template to iterate
    # pass active_game separately so the Resume button is independent of the editing selection
    user_store = get_user_store()
    active_game = user_store.get("active_game") if user_store else None
    return render_template("admin_index.html.j2", games=games.get_all(), user_selected=selected_game, user_active=active_game)


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
            return redirect(url_for("admin.admin_index"))
        # failed login: re-render with an error flag (or you can flash)
        return redirect(url_for("admin_login", next=next_url, error=1))

    return render_template("admin_login.html.j2")



@admin_bp.route("/start", methods=["POST"])
def admin_start_game():
    """Stage a READY game and show the active-game page with entry code."""
    user_store = get_user_store()
    selected_game, game_id = select_game_from_form()

    if not selected_game:
        flash("Selected game not found.", "error")
        return redirect(url_for("admin.admin_index"))

    # only READY games may be started/staged
    if selected_game.state != selected_game.STATE_READY:
        flash(f"Cannot start — the game '{selected_game.name}' is in state '{selected_game.state}'. Only games in state 'ready' may be started.", "error")
        return redirect(url_for("admin.admin_index"))

    try:
        selected_game.mark_staged()
    except Exception:
        logging.exception("Failed to stage game %s", selected_game.name)
        flash("Failed to stage the selected game.", "error")
        return redirect(url_for("admin.admin_index"))

    # put staged game into this admin's user store and show active page
    user_store["selected_game"] = selected_game
    user_store["active_game"] = selected_game
    return render_template("admin_active_game.html.j2", game=selected_game, entry_code=selected_game.get_entry_code())

@admin_bp.route("/begin", methods=["POST"])
def admin_begin_game():
    """
    Start a staged game (transition to in_progress) and redirect admin to the
    current-question page which will auto-update as riddles advance.
    """
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("admin.admin_index"))

    if selected_game.state != selected_game.STATE_STAGED:
        flash(f"Cannot start — the game '{selected_game.name}' must be staged first.", "error")
        return redirect(url_for("admin.admin_index"))

    try:
        selected_game.start()
    except Exception:
        logging.exception("Failed to start game %s", selected_game.name)
        flash("Failed to start the selected game.", "error")
        return redirect(url_for("admin.admin_index"))

    # redirect to the admin page that shows the current question
    return redirect(url_for("admin.admin_current_question"))


@admin_bp.route("/current")
def admin_current_question():
    """
    Render the admin view that displays the current riddle and polls for updates.
    If the game is already complete, redirect to the admin results page.
    """
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("admin.admin_index"))

    # If the game is already complete (no current riddle), redirect to results immediately
    try:
        current = selected_game.get_riddle_at_index(selected_game.current_riddle_index)
    except Exception:
        current = None

    if current is None:
        return redirect(url_for("admin.admin_results"))

    # pass entry_code so initial render shows it immediately
    return render_template("admin_current_question.html.j2", game=selected_game, entry_code=selected_game.get_entry_code())


@admin_bp.route("/current_status")
def admin_current_status():
    """
    Return JSON describing the selected game's current riddle/state.
    Polled by the admin_current_question page.
    """
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None

    if not selected_game:
        return jsonify({"error": "no_selected_game"}), 400

    # Get current riddle (returns None when game complete or out of bounds)
    current = selected_game.get_riddle_at_index(selected_game.current_riddle_index)

    if current is None:
        return jsonify({
            "game_over": True,
            "state": selected_game.state,
            "riddle_id": None,
            "entry_code": selected_game.get_entry_code(),
        })

    return jsonify({
        "game_over": False,
        "state": selected_game.state,
        "riddle_id": selected_game.get_current_riddle_number(),
        "question": current.get_riddle(),
        "hint": current.get_hint(),
        "image_name": current.get_image_name(),
        "attempts": current.get_attempts(),
        "entry_code": selected_game.get_entry_code(),
    })
@admin_bp.route("/cancel", methods=["POST"])
def admin_cancel_game():
    """Cancel the active game: reset progress, mark READY, and return to admin index."""
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None

    if not selected_game:
        flash("No active game to cancel.", "error")
        return redirect(url_for("admin.admin_index"))

    if selected_game.state not in (selected_game.STATE_STAGED, selected_game.STATE_IN_PROGRESS):
        flash(f"Cannot cancel — the game '{selected_game.name}' is not active.", "error")
        return redirect(url_for("admin.admin_index"))

    try:
        selected_game.reset_progress()
        selected_game.mark_ready()
    except Exception:
        logging.exception("Failed to cancel game %s", selected_game.name)
        flash("Failed to cancel the game.", "error")
        return redirect(url_for("admin.admin_current_question"))

    user_store["active_game"] = None
    flash("Game cancelled.", "info")
    return redirect(url_for("admin.admin_index"))


@admin_bp.route("/resume", methods=["POST"])
def admin_resume_game():
    """Resume the active game previously started by this admin (stored in their user store)."""
    user_store = get_user_store()
    selected_game = user_store.get("active_game")
    if not selected_game:
        flash("No active game to resume.", "error")
        return redirect(url_for("admin.admin_index"))
    if selected_game.state not in (selected_game.STATE_STAGED, selected_game.STATE_IN_PROGRESS):
        flash(f"Cannot resume — the game '{selected_game.name}' is not active.", "error")
        return redirect(url_for("admin.admin_index"))
    if selected_game.state == selected_game.STATE_IN_PROGRESS:
        return redirect(url_for("admin.admin_current_question"))
    return render_template("admin_active_game.html.j2", game=selected_game, entry_code=selected_game.get_entry_code())


# python
@app.route("/results")
def results():
    """
    User-facing results page shown when a player reaches the end of the game.
    Shows total duration and per-user correct counts (with display names).
    """
    user_store = get_user_store()
    selected_game = user_store.get("selected_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("index"))

    # compute duration: use end_time if present, otherwise compute up to now
    start = selected_game.start_time
    end = selected_game.end_time
    duration_secs = None
    if start:
        effective_end = end or datetime.now(timezone.utc)
        duration_secs = int((effective_end - start).total_seconds())

    # build a list of (display_name, correct_count)
    scores = []
    for uid, count in selected_game.user_scores.items():
        display = USER_DATA.get(uid, {}).get("display_name", uid)
        scores.append({"user_id": uid, "display_name": display, "correct": count})

    # ensure the current user is included even if they scored zero
    cur_uid = session.get("user_id")
    if cur_uid and cur_uid not in selected_game.user_scores:
        display = USER_DATA.get(cur_uid, {}).get("display_name", cur_uid)
        scores.append({"user_id": cur_uid, "display_name": display, "correct": 0})

    # sort by correct desc
    scores = sorted(scores, key=lambda s: (-s["correct"], s["display_name"]))

    def _format_duration(secs):
        if secs is None:
            return None
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}h {m:d}m {s:d}s"
        if m:
            return f"{m:d}m {s:d}s"
        return f"{s:d}s"

    return render_template("user_results.html.j2",
                           game=selected_game,
                           duration_seconds=duration_secs,
                           duration_text=_format_duration(duration_secs),
                           scores=scores,
                           user_name=get_user_name())


# python
@admin_bp.route("/results")
def admin_results():
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None

    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("admin.admin_index"))

    # compute duration: use end_time if present, otherwise compute up to now
    start = selected_game.start_time
    end = selected_game.end_time
    duration_secs = None
    if start:
        effective_end = end or datetime.now(timezone.utc)
        duration_secs = int((effective_end - start).total_seconds())

    scores = []
    for uid, count in selected_game.user_scores.items():
        display = USER_DATA.get(uid, {}).get("display_name", uid)
        scores.append({"user_id": uid, "display_name": display, "correct": count})
    scores = sorted(scores, key=lambda s: (-s["correct"], s["display_name"]))

    def _format_duration(secs):
        if secs is None:
            return None
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:d}h {m:d}m {s:d}s"
        if m:
            return f"{m:d}m {s:d}s"
        return f"{s:d}s"

    return render_template("admin_results.html.j2",
                           game=selected_game,
                           duration_seconds=duration_secs,
                           duration_text=_format_duration(duration_secs),
                           scores=scores,
                           user_name=get_user_name())

@admin_bp.route("/results/restart", methods=["POST"])
def admin_results_restart():
    """
    Restart the selected game: reset progress and mark READY so it can be staged again.
    """
    user_store = get_user_store()
    selected_game = user_store.get("active_game") if user_store else None
    if not selected_game:
        flash("No game selected.", "error")
        return redirect(url_for("admin.admin_index"))

    try:
        selected_game.reset_progress()
        selected_game.mark_ready()
    except Exception:
        logging.exception("Failed to restart selected game")
        flash("Failed to restart the game.", "error")
        return redirect(url_for("admin.admin_results"))

    user_store["active_game"] = None
    flash("Game restarted.", "info")
    return redirect(url_for("admin.admin_index"))

# register admin blueprint
app.register_blueprint(admin_bp)

if __name__ == "__main__":
    logging.info("Starting vermuten...")
    app.run()
