import json
import logging
import os
from application.Riddle import Riddle, Game


class ConfigLoadException(Exception):
    pass


class ConfigLoader(object):
    def __init__(self, path_to_json_config):
        self.path_to_json_config = path_to_json_config
        self.riddle_collection = dict()
        self.incorrect_responses = []
        self.correct_responses = []
        self.completion_message = ""
        self.completion_image_name = ""
        self._load_config()

    def _load_config(self):
        try:
            logging.info(f"Loading {self.path_to_json_config}.")
            with open(self.path_to_json_config, "r") as config_file:
                json_config = json.load(config_file)
            logging.debug(f"Config:\n{json_config}")
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
            raise ConfigLoadException from err

    def get_riddles(self):
        return self.riddle_collection

    def get_config_file_name(self):
        filename = os.path.basename(self.path_to_json_config)
        return os.path.splitext(filename)[0]
