import unittest
from application.Riddle import Riddle, Game, Games
from application.JsonLoader import ConfigLoader


class RiddleTests(unittest.TestCase):

    RIDDLE = "riddle"
    ANSWER = ["answer"]
    CORRECT_ANSWER = "answer"
    INCORRECT_ANSWER = "not answer"
    HINT = "HINT"
    IMAGE_NAME = "image_name.jpg"
    CORRECT_RESPONSES = ["yes"]
    INCORRECT_RESPONSES = ["no"]
    COMPLETION_MESSAGE = "done"
    COMPLETION_IMAGE_NAME = "all_done.png"

    def setUp(self):
        self.riddle = Riddle(
            self.RIDDLE,
            self.ANSWER,
            self.HINT,
            self.IMAGE_NAME,
            self.CORRECT_RESPONSES,
            self.INCORRECT_RESPONSES,
            self.COMPLETION_MESSAGE,
            self.COMPLETION_IMAGE_NAME,
        )

    def test_get_riddle(self):
        self.assertEqual(self.riddle.get_riddle(), self.RIDDLE)

    def test_correct_answer(self):
        self.assertTrue(self.riddle.test_answer(self.CORRECT_ANSWER))

    def test_incorrect_answer(self):
        self.assertFalse(self.riddle.test_answer(self.INCORRECT_ANSWER))

    def test_attempt_counter(self):
        self.riddle.test_answer(self.CORRECT_ANSWER)
        self.riddle.test_answer(self.INCORRECT_ANSWER)
        self.assertEqual(self.riddle.get_attempts(), 2)
        self.riddle.reset_attempts()
        self.assertEqual(self.riddle.get_attempts(), 0)

    def test_get_hint(self):
        self.assertEqual(self.riddle.get_hint(), self.HINT)

    def test_get_image_name(self):
        self.assertEqual(self.riddle.get_image_name(), self.IMAGE_NAME)

    def test_get_correct_response(self):
        self.assertIn(self.riddle.get_random_correct_response(), self.CORRECT_RESPONSES)

    def test_get_incorrect_response(self):
        self.assertIn(
            self.riddle.get_random_incorrect_response(), self.INCORRECT_RESPONSES
        )

    def test_get_completion_message(self):
        self.assertEqual(self.riddle.get_completion_message(), self.COMPLETION_MESSAGE)

    def test_get_completion_image_name(self):
        self.assertEqual(self.riddle.get_completion_image_name(), self.COMPLETION_IMAGE_NAME)

    def test_answer_case_insensitive(self):
        """Answers should match regardless of case."""
        self.assertTrue(self.riddle.test_answer("ANSWER"))
        self.assertTrue(self.riddle.test_answer("Answer"))

    def test_answer_with_whitespace(self):
        """Leading/trailing whitespace should be stripped before comparison."""
        self.assertTrue(self.riddle.test_answer("  answer  "))

    def test_answer_none_returns_false(self):
        self.assertFalse(self.riddle.test_answer(None))

    def test_to_json(self):
        data = self.riddle.to_json()
        self.assertEqual(data["question"], self.RIDDLE)
        self.assertEqual(data["answer"], self.ANSWER)
        self.assertEqual(data["hint"], self.HINT)
        self.assertEqual(data["image_name"], self.IMAGE_NAME)

    def test_multiple_answers(self):
        """A riddle with multiple accepted answers should accept any of them."""
        multi = Riddle(
            "Multi", ["egg", "eggs"], "hint", "img.png",
            ["yes"], ["no"], "done", "done.png",
        )
        self.assertTrue(multi.test_answer("egg"))
        self.assertTrue(multi.test_answer("Eggs"))
        self.assertFalse(multi.test_answer("bacon"))


class GamesTests(unittest.TestCase):

    RIDDLE = "riddle"
    ANSWER = ["answer"]
    HINT = "HINT"
    IMAGE_NAME = "image_name.jpg"

    def setUp(self):
        # single riddle used inside games
        self.riddle = Riddle(
            self.RIDDLE,
            self.ANSWER,
            self.HINT,
            self.IMAGE_NAME,
            ["yes"],
            ["no"],
            "done",
            "all_done.png",
        )
        # create Game instances with names that will sort differently
        self.game_alpha = Game("Alpha", [self.riddle])
        self.game_beta = Game("beta", [self.riddle])

    def test_get_all_sorted(self):
        g = Games([self.game_beta, self.game_alpha])
        all_games = g.get_all()
        # names should be sorted case-insensitively -> Alpha then beta
        self.assertEqual(all_games[0].name, "Alpha")
        self.assertEqual(all_games[1].name, "beta")

    def test_add_keeps_sorted(self):
        g = Games()
        g.add(self.game_beta)
        g.add(self.game_alpha)
        names = [gg.name for gg in g.get_all()]
        self.assertEqual(names, ["Alpha", "beta"])

    def test_remove_by_object_and_name(self):
        g = Games([self.game_alpha, self.game_beta])
        # remove by object
        removed = g.remove(self.game_alpha)
        self.assertTrue(removed)
        self.assertEqual(len(g), 1)
        # remove by name (case-insensitive)
        removed_name = g.remove("BETA")
        self.assertTrue(removed_name)
        self.assertEqual(len(g), 0)

    def test_find_and_len_and_iter(self):
        g = Games([self.game_beta, self.game_alpha])
        found = g.find("ALPHA")
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Alpha")
        # __len__ and iteration
        self.assertEqual(len(g), 2)
        iter_names = [gg.name for gg in g]
        self.assertEqual(iter_names, ["Alpha", "beta"])

    def test_clear(self):
        g = Games([self.game_alpha, self.game_beta])
        g.clear()
        self.assertEqual(len(g), 0)


class JsonLoaderTests(unittest.TestCase):
    CONFIG_FILE_NAME = "./tests/test_config.json"
    CONFIG_NAME = "test_config"

    def setUp(self):
        self.json_config_loader = ConfigLoader(self.CONFIG_FILE_NAME)

    def test_config_load(self):
        self.assertIsNotNone(self.json_config_loader)

    def test_get_game(self):
        # ConfigLoader creates a Game instance and exposes it as `.game`
        game = getattr(self.json_config_loader, "game", None)
        self.assertIsNotNone(game)
        self.assertEqual(type(game), Game)

    def test_get_config_file_name(self):
        self.assertEqual(
            self.json_config_loader.get_config_file_name(), self.CONFIG_NAME
        )

    def test_get_riddles_type(self):
        self.assertEqual(type(self.json_config_loader.get_riddles()), type(dict()))

    def test_get_riddles_count(self):
        self.assertEqual(len(self.json_config_loader.get_riddles()), 3)
