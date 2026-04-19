"""
Integration tests for Flask routes.

Uses Flask's test client to exercise HTTP endpoints end-to-end without
starting a real server.  Covers the public game flow (index, join, wait,
riddle, results) and the admin lifecycle (login, index, questions,
start, begin, current, cancel, resume, results, restart).
"""
import os
import unittest
from datetime import datetime, timezone

# Set env vars BEFORE importing app so it doesn't blow up on missing config
os.environ.setdefault("VERMUTEN_CONFIG", "./tests/test_config.json")
os.environ.setdefault("ADMIN_USER", "admin")
# werkzeug pbkdf2 hash of "password"
from werkzeug.security import generate_password_hash
os.environ["ADMIN_PASS_HASH"] = generate_password_hash("password", method="pbkdf2:sha256")

from app import app, games, USER_DATA  # noqa: E402
from application.Riddle import Game, Riddle  # noqa: E402


def _make_riddle(question="Q", answer=None):
    return Riddle(
        question, answer or ["A"], "hint", "img.png",
        ["Correct!"], ["Wrong!"], "Done", "done.png",
    )


class FlaskTestBase(unittest.TestCase):
    """Shared helpers: test client, admin login, game factories."""

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()
        # clear global state between tests
        USER_DATA.clear()
        # reset games to a single fresh game with 2 riddles
        games.clear()
        self.test_game = Game("TestGame", [_make_riddle("Q1", ["a1"]), _make_riddle("Q2", ["a2"])])
        games.add(self.test_game)

    def _admin_login(self):
        """Log in as admin and return the session client."""
        return self.client.post("/admin/login", data={
            "user": "admin",
            "password": "password",
        }, follow_redirects=False)

    def _admin_get(self, path, **kw):
        """GET an admin route (auto-login first)."""
        self._admin_login()
        return self.client.get(path, **kw)

    def _admin_post(self, path, **kw):
        """POST an admin route (auto-login first)."""
        self._admin_login()
        return self.client.post(path, **kw)


# ─── Public routes ───────────────────────────────────────────────────────────

class IndexTests(FlaskTestBase):

    def test_index_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_index_shows_no_active_games_initially(self):
        resp = self.client.get("/")
        # game is in READY state, so it should NOT appear on the public index
        self.assertNotIn(b"TestGame", resp.data)

    def test_index_shows_staged_game(self):
        self.test_game.mark_staged()
        resp = self.client.get("/")
        self.assertIn(b"TestGame", resp.data)


class JoinGameTests(FlaskTestBase):

    def test_join_without_game_id_redirects(self):
        resp = self.client.post("/join", data={}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_join_with_wrong_code_redirects(self):
        self.test_game.mark_staged()
        resp = self.client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": "WRONG",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_join_staged_game_goes_to_wait(self):
        self.test_game.mark_staged()
        resp = self.client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": self.test_game.get_entry_code(),
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/wait", resp.headers["Location"])

    def test_join_in_progress_game_goes_to_riddle(self):
        self.test_game.mark_staged()
        self.test_game.start()
        resp = self.client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": self.test_game.get_entry_code(),
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/riddle", resp.headers["Location"])


class WaitTests(FlaskTestBase):

    def _join(self):
        """Join a staged game so the session has a selected_game."""
        self.test_game.mark_staged()
        self.client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": self.test_game.get_entry_code(),
        })

    def test_wait_returns_200(self):
        self._join()
        resp = self.client.get("/wait")
        self.assertEqual(resp.status_code, 200)

    def test_wait_status_returns_json(self):
        self._join()
        resp = self.client.get("/wait_status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("state", data)

    def test_wait_redirects_if_in_progress(self):
        self._join()
        self.test_game.start()
        resp = self.client.get("/wait", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/riddle", resp.headers["Location"])


class RiddleFlowTests(FlaskTestBase):

    def _join_started_game(self):
        """Join and start a game so the user can answer riddles."""
        self.test_game.mark_staged()
        self.test_game.start()
        self.client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": self.test_game.get_entry_code(),
        })

    def test_riddle_page_returns_200(self):
        self._join_started_game()
        resp = self.client.get("/riddle")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Q1", resp.data)

    def test_correct_answer_advances(self):
        self._join_started_game()
        resp = self.client.post("/riddle", data={"guess": "a1"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        # should now be on Q2
        self.assertIn(b"Q2", resp.data)

    def test_incorrect_answer_stays(self):
        self._join_started_game()
        resp = self.client.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Q1", resp.data)

    def test_completing_all_riddles_redirects_to_results(self):
        self._join_started_game()
        self.client.post("/riddle", data={"guess": "a1"})
        resp = self.client.post("/riddle", data={"guess": "a2"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/riddle", resp.headers["Location"])
        # following redirects should land on results
        resp2 = self.client.get("/riddle", follow_redirects=False)
        self.assertEqual(resp2.status_code, 302)
        self.assertIn("/results", resp2.headers["Location"])


# ─── Admin routes ────────────────────────────────────────────────────────────

class AdminLoginTests(FlaskTestBase):

    def test_login_page_returns_200(self):
        resp = self.client.get("/admin/login")
        self.assertEqual(resp.status_code, 200)

    def test_successful_login_redirects_to_admin_index(self):
        resp = self._admin_login()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin", resp.headers["Location"])

    def test_bad_password_redirects_with_error(self):
        resp = self.client.post("/admin/login", data={
            "user": "admin",
            "password": "wrong",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("error=1", resp.headers["Location"])

    def test_admin_pages_require_login(self):
        resp = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.headers["Location"])


class AdminIndexTests(FlaskTestBase):

    def test_admin_index_returns_200(self):
        resp = self._admin_get("/admin/")
        self.assertEqual(resp.status_code, 200)

    def test_admin_index_lists_games(self):
        resp = self._admin_get("/admin/")
        self.assertIn(b"TestGame", resp.data)


class AdminQuestionsTests(FlaskTestBase):

    def test_questions_page_returns_200(self):
        resp = self._admin_get("/admin/questions?game_id=TestGame")
        self.assertEqual(resp.status_code, 200)

    def test_create_new_game(self):
        resp = self._admin_post("/admin/questions", data={
            "create_new": "1",
            "new_game_name": "BrandNew",
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIsNotNone(games.find("BrandNew"))

    def test_cannot_edit_in_progress_game(self):
        self.test_game.mark_staged()
        resp = self._admin_post("/admin/questions", data={
            "game_id": "TestGame",
        }, follow_redirects=True)
        # should redirect back to admin index with a flash
        self.assertEqual(resp.status_code, 200)


class AdminGameLifecycleTests(FlaskTestBase):
    """Start → begin → current → results → restart."""

    def test_start_stages_game(self):
        resp = self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.test_game.state, Game.STATE_STAGED)

    def test_start_already_staged_fails(self):
        self.test_game.mark_staged()
        resp = self._admin_post("/admin/start", data={"game_id": "TestGame"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        # game stays staged, no crash

    def test_begin_starts_game(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        resp = self._admin_post("/admin/begin", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.test_game.state, Game.STATE_IN_PROGRESS)

    def test_current_question_returns_200(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self._admin_post("/admin/begin")
        resp = self._admin_get("/admin/current")
        self.assertEqual(resp.status_code, 200)

    def test_current_status_returns_json(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self._admin_post("/admin/begin")
        resp = self._admin_get("/admin/current_status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("riddle_id", data)
        self.assertFalse(data["game_over"])


class AdminCancelGameTests(FlaskTestBase):

    def test_cancel_resets_game_to_ready(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self._admin_post("/admin/begin")
        self.assertEqual(self.test_game.state, Game.STATE_IN_PROGRESS)

        resp = self._admin_post("/admin/cancel", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.test_game.state, Game.STATE_READY)
        self.assertIsNone(self.test_game.entry_code)

    def test_cancel_without_active_game_redirects(self):
        resp = self._admin_post("/admin/cancel", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_cancel_staged_game(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self.assertEqual(self.test_game.state, Game.STATE_STAGED)
        resp = self._admin_post("/admin/cancel", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.test_game.state, Game.STATE_READY)


class AdminResumeGameTests(FlaskTestBase):

    def test_resume_staged_shows_active_game(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        resp = self._admin_post("/admin/resume")
        self.assertEqual(resp.status_code, 200)

    def test_resume_in_progress_redirects_to_current(self):
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self._admin_post("/admin/begin")
        resp = self._admin_post("/admin/resume", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/current", resp.headers["Location"])

    def test_resume_without_active_game_redirects(self):
        resp = self._admin_post("/admin/resume", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)


class AdminResultsTests(FlaskTestBase):

    def _complete_game(self):
        """Stage, start, and advance past all riddles."""
        self._admin_post("/admin/start", data={"game_id": "TestGame"})
        self._admin_post("/admin/begin")
        # advance riddles
        self.test_game.next_riddle()
        self.test_game.next_riddle()

    def test_results_page_after_completion(self):
        self._complete_game()
        resp = self._admin_get("/admin/results")
        self.assertEqual(resp.status_code, 200)

    def test_restart_resets_and_redirects(self):
        self._complete_game()
        resp = self._admin_post("/admin/results/restart", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.test_game.state, Game.STATE_READY)


class RateLimitTests(FlaskTestBase):
    """Rate limiting must be per-user: one user's spam must not block another."""

    def _start_game(self):
        self.test_game.mark_staged()
        self.test_game.start()

    def _join(self, client):
        client.post("/join", data={
            "game_id": "TestGame",
            "entry_code": self.test_game.get_entry_code(),
        })

    def test_rate_limit_is_per_user(self):
        self._start_game()

        # Two independent sessions (two different players)
        user_a = app.test_client()
        user_b = app.test_client()
        self._join(user_a)
        self._join(user_b)

        # User A: spam 4 wrong answers quickly to trigger rate limiting
        for _ in range(4):
            user_a.post("/riddle", data={"guess": "wrong"})

        # User A should now be rate-limited: submitting another guess shows cooldown
        resp_a = user_a.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertIn(b"please wait", resp_a.data.lower())

        # User B should NOT be rate-limited and can still guess normally
        resp_b = user_b.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertNotIn(b"please wait", resp_b.data.lower())
        # User B should still see the riddle
        self.assertIn(b"Q1", resp_b.data)

    def test_rate_limit_resets_on_new_question(self):
        self._start_game()
        user_a = app.test_client()
        self._join(user_a)

        # Trigger rate limiting
        for _ in range(4):
            user_a.post("/riddle", data={"guess": "wrong"})

        # Now answer correctly to advance to next question
        user_a.post("/riddle", data={"guess": "a1"}, follow_redirects=True)

        # On the new question, user should NOT be rate-limited
        resp = user_a.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertNotIn(b"please wait", resp.data.lower())
        self.assertIn(b"Q2", resp.data)

    def test_fifth_wrong_answer_causes_16_second_delay(self):
        """After 3 wrongs → 4s, 4th wrong → 8s, 5th wrong → 16s."""
        self._start_game()
        user = app.test_client()
        self._join(user)

        # Wrongs 1-3: the 3rd triggers a 4-second cooldown
        for _ in range(3):
            user.post("/riddle", data={"guess": "wrong"})

        with user.session_transaction() as sess:
            uid = sess["user_id"]
        store = USER_DATA[uid]
        self.assertEqual(store["rl_delay"], 4, "3rd wrong answer should set delay to 4s")
        # expire the lockout
        store["rl_locked_until"] = datetime(2000, 1, 1, tzinfo=timezone.utc)

        # Wrong 4: cooldown expired, so this goes through and escalates to 8s
        resp4 = user.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertEqual(store["rl_delay"], 8, "4th wrong answer should escalate delay to 8s")
        self.assertIn(b"Wait 8s", resp4.data)

        # expire the 8s lockout AND clear old timestamps to simulate real elapsed time
        # (in production, >10s will have passed so timestamps fall out of the window)
        store["rl_locked_until"] = datetime(2000, 1, 1, tzinfo=timezone.utc)
        store["rl_wrong_times"] = []

        # Wrong 5: must still escalate to 16s because rl_delay is already active
        resp5 = user.post("/riddle", data={"guess": "wrong"}, follow_redirects=True)
        self.assertEqual(store["rl_delay"], 16, "5th wrong answer should escalate delay to 16s")
        self.assertIn(b"Wait 16s", resp5.data)


if __name__ == "__main__":
    unittest.main()


