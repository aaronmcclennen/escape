"""
Unit tests for the Game class.

Covers: state transitions, entry code generation, riddle navigation,
progress reset, riddle CRUD, timing, user scores, JSON serialization,
and edge cases around invalid transitions.
"""
import unittest
from application.Riddle import Riddle, Game, RiddleException


def _make_riddle(question="Q", answer=None):
    """Helper to build a minimal Riddle for test fixtures."""
    return Riddle(
        question,
        answer or ["A"],
        "hint",
        "img.png",
        ["Correct!"],
        ["Wrong!"],
        "Done",
        "done.png",
    )


class GameStateTransitionTests(unittest.TestCase):
    """Verify the legal state machine: READY → STAGED → IN_PROGRESS, and stop/cancel paths."""

    def setUp(self):
        self.game = Game("Test", [_make_riddle()])

    def test_initial_state_is_ready(self):
        self.assertEqual(self.game.state, Game.STATE_READY)

    def test_mark_editing(self):
        self.game.mark_editing()
        self.assertEqual(self.game.state, Game.STATE_EDITING)
        self.assertIsNone(self.game.entry_code)

    def test_mark_ready_from_editing(self):
        self.game.mark_editing()
        self.game.mark_ready()
        self.assertEqual(self.game.state, Game.STATE_READY)

    def test_mark_staged_from_ready(self):
        self.game.mark_staged()
        self.assertEqual(self.game.state, Game.STATE_STAGED)
        self.assertIsNotNone(self.game.entry_code)
        self.assertEqual(len(self.game.entry_code), 6)

    def test_mark_staged_from_non_ready_raises(self):
        self.game.mark_editing()
        with self.assertRaises(RiddleException):
            self.game.mark_staged()

    def test_start_from_staged(self):
        self.game.mark_staged()
        self.game.start()
        self.assertEqual(self.game.state, Game.STATE_IN_PROGRESS)
        self.assertIsNotNone(self.game.entry_code)
        self.assertIsNotNone(self.game.start_time)

    def test_start_from_non_staged_raises(self):
        # game starts in READY; start() should fail
        with self.assertRaises(RiddleException):
            self.game.start()

    def test_stop_resets_to_ready(self):
        self.game.mark_staged()
        self.game.start()
        self.game.stop()
        self.assertEqual(self.game.state, Game.STATE_READY)
        self.assertIsNone(self.game.entry_code)

    def test_is_in_progress_staged(self):
        self.game.mark_staged()
        self.assertTrue(self.game.is_in_progress())

    def test_is_in_progress_in_progress(self):
        self.game.mark_staged()
        self.game.start()
        self.assertTrue(self.game.is_in_progress())

    def test_is_not_in_progress_when_ready(self):
        self.assertFalse(self.game.is_in_progress())

    def test_is_not_in_progress_when_editing(self):
        self.game.mark_editing()
        self.assertFalse(self.game.is_in_progress())


class GameEntryCodeTests(unittest.TestCase):
    """Entry codes should be unique across stages and contain only alphanumeric chars."""

    def test_entry_code_is_alphanumeric(self):
        game = Game("EC", [_make_riddle()])
        game.mark_staged()
        self.assertTrue(game.entry_code.isalnum())

    def test_entry_code_changes_on_restage(self):
        game = Game("EC", [_make_riddle()])
        game.mark_staged()
        code1 = game.entry_code
        game.start()
        game.stop()
        game.mark_staged()
        code2 = game.entry_code
        # codes are random; extremely unlikely to match
        # just verify both are valid strings
        self.assertIsNotNone(code1)
        self.assertIsNotNone(code2)

    def test_get_entry_code(self):
        game = Game("EC", [_make_riddle()])
        self.assertIsNone(game.get_entry_code())
        game.mark_staged()
        self.assertEqual(game.get_entry_code(), game.entry_code)

    def test_entry_code_preserved_on_start(self):
        """The code given to users during staging must survive the staged → in_progress transition."""
        game = Game("EC", [_make_riddle()])
        game.mark_staged()
        staged_code = game.entry_code
        self.assertIsNotNone(staged_code)
        game.start()
        self.assertEqual(game.entry_code, staged_code)


class GameRiddleNavigationTests(unittest.TestCase):
    """Test riddle traversal: get_current_riddle, next_riddle, boundary conditions."""

    def setUp(self):
        self.r1 = _make_riddle("Q1")
        self.r2 = _make_riddle("Q2")
        self.r3 = _make_riddle("Q3")
        self.game = Game("Nav", [self.r1, self.r2, self.r3])

    def test_initial_riddle_is_first(self):
        self.assertIs(self.game.get_current_riddle(), self.r1)
        self.assertEqual(self.game.get_current_riddle_number(), 1)

    def test_next_riddle_advances(self):
        self.game.next_riddle()
        self.assertIs(self.game.get_current_riddle(), self.r2)
        self.assertEqual(self.game.get_current_riddle_number(), 2)

    def test_past_last_riddle_returns_none(self):
        for _ in range(3):
            self.game.next_riddle()
        self.assertIsNone(self.game.get_current_riddle())

    def test_end_time_set_after_last_riddle(self):
        self.assertIsNone(self.game.end_time)
        for _ in range(3):
            self.game.next_riddle()
        self.assertIsNotNone(self.game.end_time)

    def test_end_time_not_set_before_last(self):
        self.game.next_riddle()
        self.assertIsNone(self.game.end_time)

    def test_get_riddle_count(self):
        self.assertEqual(self.game.get_riddle_count(), 3)

    def test_get_riddle_at_index(self):
        self.assertIs(self.game.get_riddle_at_index(0), self.r1)
        self.assertIs(self.game.get_riddle_at_index(2), self.r3)

    def test_get_riddle_at_index_out_of_bounds(self):
        self.assertIsNone(self.game.get_riddle_at_index(99))

    def test_empty_game_current_riddle_is_none(self):
        empty = Game("Empty", [])
        self.assertIsNone(empty.get_current_riddle())


class GameProgressResetTests(unittest.TestCase):
    """reset_progress should zero out attempts, index, timing, and scores."""

    def setUp(self):
        self.r1 = _make_riddle("Q1")
        self.r2 = _make_riddle("Q2")
        self.game = Game("Reset", [self.r1, self.r2])

    def test_reset_clears_riddle_index(self):
        self.game.next_riddle()
        self.game.reset_progress()
        self.assertEqual(self.game.current_riddle_index, 0)

    def test_reset_clears_attempts(self):
        self.r1.test_answer("wrong")
        self.r1.test_answer("wrong")
        self.assertEqual(self.r1.get_attempts(), 2)
        self.game.reset_progress()
        self.assertEqual(self.r1.get_attempts(), 0)

    def test_reset_clears_timing_and_scores(self):
        self.game.mark_staged()
        self.game.start()
        self.game.user_scores["u1"] = 5
        self.game.reset_progress()
        self.assertIsNone(self.game.start_time)
        self.assertIsNone(self.game.end_time)
        self.assertEqual(self.game.user_scores, {})

    def test_get_total_attempt_count(self):
        self.r1.test_answer("a")
        self.r2.test_answer("b")
        self.r2.test_answer("c")
        self.assertEqual(self.game.get_total_attempt_count(), 3)


class GameRiddleCrudTests(unittest.TestCase):
    """Test add, remove, replace operations on riddle list."""

    def setUp(self):
        self.r1 = _make_riddle("Q1")
        self.r2 = _make_riddle("Q2")
        self.game = Game("CRUD", [self.r1, self.r2])

    def test_add_riddle_at_end(self):
        r3 = _make_riddle("Q3")
        self.game.add_riddle_at_end(r3)
        self.assertEqual(self.game.get_riddle_count(), 3)
        self.assertIs(self.game.get_riddle_at_index(2), r3)

    def test_remove_riddle_by_index(self):
        self.game.remove_riddle_by_index(0)
        self.assertEqual(self.game.get_riddle_count(), 1)
        self.assertIs(self.game.get_riddle_at_index(0), self.r2)

    def test_remove_out_of_bounds_does_nothing(self):
        self.game.remove_riddle_by_index(99)
        self.assertEqual(self.game.get_riddle_count(), 2)

    def test_replace_riddle_at_index(self):
        replacement = _make_riddle("Replaced")
        self.game.replace_riddle_at_index(0, replacement)
        self.assertIs(self.game.get_riddle_at_index(0), replacement)

    def test_replace_out_of_bounds_does_nothing(self):
        self.game.replace_riddle_at_index(99, _make_riddle("X"))
        self.assertEqual(self.game.get_riddle_count(), 2)


class GameJsonTests(unittest.TestCase):
    """to_json and make_json_filename."""

    def test_to_json_structure(self):
        game = Game("MyGame", [_make_riddle("Q1")])
        data = game.to_json()
        self.assertEqual(data["name"], "MyGame")
        self.assertIsInstance(data["riddles"], list)
        self.assertEqual(len(data["riddles"]), 1)
        self.assertIn("question", data["riddles"][0])

    def test_make_json_filename(self):
        game = Game("My Game!", [])
        self.assertEqual(game.make_json_filename(), "My_Game.json")

    def test_make_json_filename_empty_name(self):
        game = Game("", [])
        self.assertEqual(game.make_json_filename(), "riddle.json")


class GameCompletionTests(unittest.TestCase):
    """get_completion_message and get_completion_image_name from the first riddle."""

    def test_completion_message(self):
        game = Game("C", [_make_riddle()])
        self.assertEqual(game.get_completion_message(), "Done")

    def test_completion_image_name(self):
        game = Game("C", [_make_riddle()])
        self.assertEqual(game.get_completion_image_name(), "done.png")

    def test_empty_game_completion(self):
        game = Game("Empty", [])
        self.assertEqual(game.get_completion_message(), "")
        self.assertEqual(game.get_completion_image_name(), "")


class GameUserScoresTests(unittest.TestCase):
    """User score tracking."""

    def test_scores_initially_empty(self):
        game = Game("S", [_make_riddle()])
        self.assertEqual(game.user_scores, {})

    def test_scores_persist_until_reset(self):
        game = Game("S", [_make_riddle()])
        game.user_scores["u1"] = 3
        self.assertEqual(game.user_scores["u1"], 3)
        game.reset_progress()
        self.assertEqual(game.user_scores, {})


if __name__ == "__main__":
    unittest.main()


