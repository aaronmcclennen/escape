import json
import logging
import os
from application.Riddle import Riddle, RiddleManager, Game


class ConfigLoadException(Exception):
    pass


class ConfigLoader(object):
    def __init__(self, path_to_json_config):
        self.path_to_json_config = path_to_json_config
        self.riddle_collection = dict()
        # store global fields so we can write them back later
        self.incorrect_responses = []
        self.correct_responses = []
        self.completion_message = ""
        self.completion_image_name = ""
        self._load_config()

    def _load_config(self):
        try:
            logging.info(f"Loading {self.path_to_json_config}.")
            config_file = open(self.path_to_json_config, "r")
            json_config = json.loads(config_file.read())
            config_file.close()
            logging.debug(f"Config:\n{json_config}")
            # remember global fields for save
            self.incorrect_responses = json_config.get("incorrect_responses", [])
            self.correct_responses = json_config.get("correct_responses", [])
            self.completion_message = json_config.get("completion_message", "")
            self.completion_image_name = json_config.get("completion_image_name", "")
            for riddle in json_config["riddles"]:
                logging.debug(f"Creating riddle object for {riddle}.")
                riddle_object = Riddle(
                    riddle["question"],
                    riddle["answer"],
                    riddle.get("hint", ""),
                    riddle.get("image_name", ""),
                    self.correct_responses,
                    self.incorrect_responses,
                    self.completion_message,
                    self.completion_image_name,
                )
                self.riddle_collection[len(self.riddle_collection)] = riddle_object
            # determine game name: use top-level "name" if present, otherwise filename without extension
            file_base = os.path.splitext(os.path.basename(self.path_to_json_config))[0]
            game_name = json_config.get("name") or file_base
            # build ordered riddle list for Game
            riddles_list = [self.riddle_collection[i] for i in range(len(self.riddle_collection))]
            # expose Game object
            self.game = Game(game_name, riddles_list)

            logging.info(f"Successfully loaded {self.path_to_json_config}.")
            logging.info(f"Riddle count: {len(self.riddle_collection)}")
            logging.info(f"Incorrect response count: {len(self.incorrect_responses)}")
            logging.info(f"Correct response count: {len(self.correct_responses)}")
        except Exception as err:
            logging.error(f"{err}")
            raise ConfigLoadException

    def get_riddles(self):
        return self.riddle_collection

    def get_riddle_manager(self):
        riddle_manager = RiddleManager(self.get_riddles())
        return riddle_manager

    def get_config_file_name(self):
        filename = os.path.basename(self.path_to_json_config)
        return filename.split(".")[0]

    # --- new methods: persist and manage riddles ---
    def _build_config_dict(self):
        riddles = []
        # preserve order 0..n-1
        for i in range(len(self.riddle_collection)):
            r = self.riddle_collection[i]
            riddles.append(
                {
                    "question": r.get_riddle(),
                    "answer": r.answer,
                    "hint": r.get_hint(),
                    "image_name": r.get_image_name(),
                }
            )
        return {
            "riddles": riddles,
            "incorrect_responses": self.incorrect_responses,
            "correct_responses": self.correct_responses,
            "completion_message": self.completion_message,
            "completion_image_name": self.completion_image_name,
        }

    def save_config(self):
        try:
            config_dict = self._build_config_dict()
            with open(self.path_to_json_config, "w") as f:
                json.dump(config_dict, f, indent=2, sort_keys=False)
            logging.info(f"Wrote updated config to {self.path_to_json_config}")
        except Exception:
            logging.exception("Failed to write config")
            raise ConfigLoadException

    def add_riddle(self, riddle_payload):
        """riddle_payload: dict with keys question, answer (list), hint, image_name"""
        idx = len(self.riddle_collection)
        r = Riddle(
            riddle_payload.get("question", ""),
            riddle_payload.get("answer", []),
            riddle_payload.get("hint", ""),
            riddle_payload.get("image_name", ""),
            self.correct_responses,
            self.incorrect_responses,
            self.completion_message,
            self.completion_image_name,
        )
        self.riddle_collection[idx] = r
        self.save_config()

    def update_riddle(self, index, riddle_payload):
        if index not in self.riddle_collection:
            raise ConfigLoadException
        r = Riddle(
            riddle_payload.get("question", ""),
            riddle_payload.get("answer", []),
            riddle_payload.get("hint", ""),
            riddle_payload.get("image_name", ""),
            self.correct_responses,
            self.incorrect_responses,
            self.completion_message,
            self.completion_image_name,
        )
        self.riddle_collection[index] = r
        self.save_config()

    def delete_riddle(self, index):
        if index not in self.riddle_collection:
            raise ConfigLoadException
        # delete and reindex to keep 0..n-1
        del self.riddle_collection[index]
        new = {}
        for i, (_, r) in enumerate(sorted(self.riddle_collection.items(), key=lambda it: int(it[0]))):
            new[i] = r
        self.riddle_collection = new
        self.save_config()
