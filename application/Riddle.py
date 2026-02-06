import logging
import random
import secrets
import string
from datetime import datetime, timezone


class RiddleException(Exception):
    pass


class Riddle(object):
    def __init__(
        self,
        riddle,
        answer,
        hint,
        image_name,
        correct_responses,
        incorrect_responses,
        completion_message,
        completion_image_name,
    ):
        self.riddle = riddle
        self.image_name = image_name
        self.answer = answer
        self.hint = hint
        self.attempts = 0
        self.correct_responses = correct_responses
        self.incorrect_responses = incorrect_responses
        self.completion_message = completion_message
        self.completion_image_name = completion_image_name

    def get_riddle(self):
        return self.riddle

    def get_hint(self):
        return self.hint

    def get_image_name(self):
        return self.image_name

    def get_attempts(self):
        return self.attempts

    def reset_attempts(self):
        self.attempts = 0

    def get_completion_message(self):
        return self.completion_message

    def get_completion_image_name(self):
        return self.completion_image_name

    def test_answer(self, response):
        logging.debug(f"Testing {response} against {self.answer}.")
        self.attempts += 1
        response = response.lower()
        if response in self.answer:
            logging.debug("Returning True.")
            return True
        else:
            logging.debug("Returning False.")
            return False

    def get_random_incorrect_response(self):
        return random.choice(self.incorrect_responses)

    def get_random_correct_response(self):
        return random.choice(self.correct_responses)

    def to_json(self):
        """Convert the riddle to a JSON-serializable format."""
        return {
            "question": self.riddle,
            "answer": self.answer,
            "hint": self.hint,
            "image_name": self.image_name,
        }


class Game(object):
    # possible states
    STATE_EDITING = "editing"
    STATE_READY = "ready"
    STATE_IN_PROGRESS = "in_progress"
    STATE_STAGED = "staged"

    def __init__(self, name, riddles):
        self.name = name
        self.riddles = riddles
        self.current_riddle_index = 0
        # state: editing | ready | in_progress
        self.state = self.STATE_READY
        # entry_code is only meaningful when state == in_progress
        self.entry_code = None

        # new: timing and per-user scoring
        self.start_time = None  # datetime when game moved to in_progress
        self.end_time = None    # datetime when game finished
        self.user_scores = {}   # map user_id -> correct_count

    def _generate_entry_code(self, length: int = 6) -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def get_current_riddle(self):
        try:
            # if list-like
            if isinstance(self.riddles, list):
                return self.riddles[self.current_riddle_index]
            # if dict-like, convert index to list order
            else:
                values = list(self.riddles.values())
                return values[self.current_riddle_index]
        except Exception:
            logging.info("There are no more riddles. Returning None to caller.")
            return None

    def get_current_riddle_number(self):
        return self.current_riddle_index + 1

    def next_riddle(self):
        """
        Advance to the next riddle. If advancing past the last riddle,
        mark end_time to indicate game completion.
        """
        self.current_riddle_index += 1
        # if we've moved past the last riddle, mark end time
        total = self.get_riddle_count()
        if self.current_riddle_index >= total:
            self.end_time = datetime.now(timezone.utc)

    def get_total_attempt_count(self):
        attempts = 0
        try:
            if isinstance(self.riddles, dict):
                iterable = self.riddles.values()
            else:
                iterable = self.riddles
            for riddle in iterable:
                try:
                    attempts += riddle.get_attempts()
                except Exception:
                    pass
        except Exception:
            logging.exception("Failed while counting attempts")
        return attempts

    def get_completion_message(self):
        try:
            if isinstance(self.riddles, list) and self.riddles:
                return self.riddles[0].get_completion_message()
            elif isinstance(self.riddles, dict) and self.riddles:
                return list(self.riddles.values())[0].get_completion_message()
        except Exception:
            pass
        return ""

    def get_completion_image_name(self):
        try:
            if isinstance(self.riddles, list) and self.riddles:
                return self.riddles[0].get_completion_image_name()
            elif isinstance(self.riddles, dict) and self.riddles:
                return list(self.riddles.values())[0].get_completion_image_name()
        except Exception:
            pass
        return ""

    def get_riddle_count(self):
        return len(self.riddles)

    def reset_progress(self):
        logging.warning("Resetting progress and attempt counts.")
        self.current_riddle_index = 0
        # reset attempts for each riddle (support dict or list)
        try:
            if isinstance(self.riddles, dict):
                iterable = self.riddles.values()
            else:
                iterable = self.riddles
            for r in iterable:
                try:
                    r.reset_attempts()
                except Exception:
                    pass
        except Exception:
            logging.exception("Failed while resetting riddle attempts")
        # entry_code only applies if game is in progress
        if self.state == self.STATE_IN_PROGRESS:
            self.entry_code = self._generate_entry_code()
        else:
            self.entry_code = None
        # clear timing and per-user scores on reset
        self.start_time = None
        self.end_time = None
        self.user_scores = {}

    def remove_riddle_by_index(self, index: int) -> None:
        """Remove riddle at given index from the game's riddle list."""
        if isinstance(self.riddles, list):
            if 0 <= index < len(self.riddles):
                del self.riddles[index]
            else:
                logging.error("remove_riddle_by_index: index %d out of range (0..%d)", index, max(0, len(self.riddles) - 1))
        else:
            raise RiddleException("Riddles are not stored in a list; cannot remove by index.")
        
    def replace_riddle_at_index(self, index: int, new_riddle) -> None:
        """
        Replace the riddle at the given index with new_riddle.
        If index is out of bounds, log an error and do nothing.
        Supports both list and dict for self.riddles.
        """
        import logging
        if isinstance(self.riddles, list):
            if index < 0 or index >= len(self.riddles):
                logging.error("replace_riddle_at_index: index %d out of range (0..%d)", index, max(0, len(self.riddles) - 1))
                return
            self.riddles[index] = new_riddle
        else:
            raise RiddleException("Riddles are not stored in a list; cannot remove by index.")

    def get_riddle_at_index(self, index: int):
        """
        Return the riddle at the given index, or None if out of bounds.
        """
        if isinstance(self.riddles, list):
            if 0 <= index < len(self.riddles):
                return self.riddles[index]
            else:
                logging.error("get_riddle_at_index: index %d out of range (0..%d)", index, max(0, len(self.riddles) - 1))
                return None
        else:
            raise RiddleException("Riddles are not stored in a list; cannot access by index.")

    def add_riddle_at_end(self, new_riddle):
        """
        Add a new riddle to the end of the game's riddle list.
        Supports both list and dict for self.riddles.
        """
        if isinstance(self.riddles, list):
            self.riddles.append(new_riddle)
        else:
            raise RiddleException("Riddles are not stored in a list; cannot add new riddle.")

    # state transitions
    def start(self):
        """Mark game in_progress and reset progress.
        Only allowed when the game is currently STATE_STAGED.
        """
        if self.state != self.STATE_STAGED:
            raise RiddleException(f"Cannot start game from state '{self.state}'; only '{self.STATE_STAGED}' may start.")
        self.state = self.STATE_IN_PROGRESS
        # reset attempt counts and user scores
        self.reset_progress()
        # set start time and fresh entry code
        self.start_time = datetime.now(timezone.utc)
        self.entry_code = self._generate_entry_code()
        self.user_scores = {}

    def stop(self):
        """Stop an in-progress game and mark it ready; clear entry code."""
        self.state = self.STATE_READY
        self.entry_code = None

    def mark_ready(self):
        """Mark game ready for starting (no entry code)."""
        self.state = self.STATE_READY
        self.entry_code = None
        # keep timing/scores cleared until actual start
        self.start_time = None
        self.end_time = None
        self.user_scores = {}

    def mark_editing(self):
        """Mark game editable (no entry code)."""
        self.state = self.STATE_EDITING
        self.entry_code = None

    def mark_staged(self):
        """
        Move a ready game into the staged state.
        Only allowed when the game is currently STATE_READY.
        Raises RiddleException if the transition is not allowed.
        """
        if self.state != self.STATE_READY:
            raise RiddleException(f"Cannot stage game from state '{self.state}'; only '{self.STATE_READY}' may be staged.")
        self.state = self.STATE_STAGED
        self.entry_code = self._generate_entry_code()
        # staged is not yet started: clear times so later start sets them
        self.start_time = None
        self.end_time = None
        self.user_scores = {}

    def is_in_progress(self) -> bool:
        """
        Consider the game 'in progress' if it is either staged or in_progress.
        """
        return self.state in (self.STATE_STAGED, self.STATE_IN_PROGRESS)

    def get_entry_code(self):
        return self.entry_code

    def to_json(self):
        """Convert the game state to a JSON-serializable format."""
        if isinstance(self.riddles, dict):
            jriddles = [riddle.to_json() for riddle in self.riddles.values()]
            logging.debug("Converted riddles from dict to list for JSON serialization.")
        else:
            jriddles = [riddle.to_json() for riddle in self.riddles]
            logging.debug("Converted riddles from list for JSON serialization." )
            logging.debug("Riddles for JSON serialization: {}".format(jriddles))
        return {
            "name": self.name,
            "riddles": jriddles
        }

    def make_json_filename(self) -> str:
        """
        Construct a valid JSON file name based on the game's name.
        If there is no name, use 'riddle.json'.
        """
        import re
        base = self.name if self.name else "riddle"
        logging.debug(f"Generating JSON filename from game name: {base}")
        # Replace spaces and non-alphanumeric characters with underscores
        base = re.sub(r'[^A-Za-z0-9]+', '_', base).strip('_')
        if not base:
            base = "riddle"
        return f"{base}.json"


import bisect
from typing import Iterable, List, Optional


class Games(object):
    """
    Container for Game objects. Keeps the internal list sorted by game.name (case-insensitive).
    get_all() returns a shallow copy of the current list.
    """

    def __init__(self, games: Optional[Iterable[Game]] = None):
        self._games: List[Game] = []
        if games:
            for g in games:
                self.add(g)

    def _key(self, game: Game) -> str:
        return (getattr(game, "name", "") or "").lower()

    def add(self, game: Game) -> None:
        """Insert game keeping the list sorted by name (case-insensitive)."""
        key = self._key(game)
        keys = [self._key(g) for g in self._games]
        pos = bisect.bisect_left(keys, key)
        self._games.insert(pos, game)

    def remove(self, game_or_name) -> bool:
        """Remove by object or by name. Returns True if removed, False otherwise."""
        name = None
        if isinstance(game_or_name, Game):
            target = game_or_name
            try:
                self._games.remove(target)
                return True
            except ValueError:
                return False
        else:
            name = (str(game_or_name) or "").lower()
            for i, g in enumerate(self._games):
                if self._key(g) == name:
                    del self._games[i]
                    return True
            return False

    def find(self, name: str) -> Optional[Game]:
        """Return first game matching name (case-insensitive) or None."""
        target = (name or "").lower()
        for g in self._games:
            if self._key(g) == target:
                return g
        return None

    def get_all(self) -> List[Game]:
        """Return a shallow copy of the sorted games list."""
        return list(self._games)

    def __iter__(self):
        return iter(self.get_all())

    def __len__(self):
        return len(self._games)

    def clear(self):
        self._games.clear()
