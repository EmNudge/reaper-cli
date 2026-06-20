"""Line-by-line ``.RPP`` parser → dataclass tree (vendored from dschuler36)."""

import os
import string

from .dataclasses import FX, AudioItem, Project, Track

# REAPER picks whichever of " ' ` (or unquoted) the value itself doesn't
# contain. The reader has to support all three quote chars.
_QUOTE_CHARS = ('"', "'", "`")
_BASE64_CHARS = frozenset(string.ascii_letters + string.digits + "+/=")


class RPPParser:
    MAX_ENCODED_DATA_LENGTH = 1024

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.project = Project(
            name=file_path.split("/")[-1].rsplit(".", 1)[0],
            location=file_path,
            tempo=0.0,
            time_signature="",
            total_length=0.0,
            tracks=[],
        )
        self.parse_file()

    def parse_file(self):
        with open(self.file_path) as f:
            lines = f.readlines()

        current_track: dict | None = None
        track_stack: list[dict] = []
        current_fx_chain: list[FX] = []
        in_fx_chain = False
        current_fx: dict | None = None
        in_item_block = False
        in_source_block = False
        current_item: dict | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("TEMPO"):
                self._parse_tempo(line)

            elif line.startswith("<TRACK"):
                current_track = self._create_empty_track()
                track_stack.append(current_track)

            elif line.startswith("NAME") and current_track:
                current_track["name"] = self._parse_name(line)

            elif line.startswith("<FXCHAIN"):
                in_fx_chain = True
                current_fx_chain = []

            elif line.startswith("<VST") and in_fx_chain:
                if current_fx:
                    current_fx_chain.append(self._create_fx(current_fx))
                current_fx = self._parse_vst_line(line)

            elif line.startswith("BYPASS") and current_fx:
                current_fx["bypassed"] = self._parse_bypass(line)

            elif in_fx_chain and current_fx and self._looks_like_base64(line):
                current_fx["encoded_data"].append(line)

            elif line == ">" and in_fx_chain:
                if current_fx:
                    current_fx_chain.append(self._create_fx(current_fx))
                    current_fx = None
                else:
                    in_fx_chain = False
                    if current_track:
                        current_track["fx_chain"] = current_fx_chain
                    current_fx_chain = []

            elif line.startswith("VOLPAN") and current_track:
                volume, pan = self._parse_volpan(line)
                current_track["volume"] = volume
                current_track["pan"] = pan

            elif line.startswith("MUTESOLO") and current_track:
                mute, solo = self._parse_mutesolo(line)
                current_track["mute"] = mute
                current_track["solo"] = solo

            elif line.startswith("<ITEM") and current_track:
                in_item_block = True
                current_item = {"position": 0.0, "length": 0.0, "audio_filepath": ""}

            elif line.startswith("POSITION") and in_item_block and current_item:
                current_item["position"] = self._parse_position(line)

            elif line.startswith("LENGTH") and in_item_block and current_item:
                current_item["length"] = self._parse_length(line)

            elif line.startswith("<SOURCE ") and in_item_block:
                # Match every source kind (WAVE, MP3, FLAC, VORBIS, MIDI, …)
                # so non-WAV audio items still get their file path captured.
                in_source_block = True

            elif line.startswith("FILE") and in_source_block and current_item:
                current_item["audio_filepath"] = self._parse_file_path(line)

            elif line == ">" and in_item_block:
                if in_source_block:
                    in_source_block = False
                elif current_item:
                    if current_track:
                        current_track["items"].append(self._create_audio_item(current_item))
                    current_item = None
                    in_item_block = False

            elif line == ">" and track_stack:
                finished_track = track_stack.pop()
                if finished_track:
                    self.project.tracks.append(self._create_track_from_dict(finished_track))
                current_track = track_stack[-1] if track_stack else None

        # Truncated / malformed RPPs may leave <TRACK> blocks unclosed at EOF.
        # Drain the stack so we at least surface every track we started reading,
        # rather than silently dropping them.
        while track_stack:
            finished_track = track_stack.pop()
            if finished_track:
                self.project.tracks.append(self._create_track_from_dict(finished_track))

    def _parse_tempo(self, line: str) -> None:
        parts = line.split()
        if len(parts) >= 3:
            self.project.tempo = float(parts[1])
            self.project.time_signature = f"{parts[2]}/{parts[3]}"

    @staticmethod
    def _create_empty_track() -> dict:
        return {
            "name": "",
            "volume": 1.0,
            "pan": 0.0,
            "mute": False,
            "solo": False,
            "type": "audio",
            "input_source": "",
            "audio_filepath": "",
            "fx_chain": [],
            "automation": {},
            "peak_level": 0.0,
            "send_levels": [],
            "items": [],
        }

    @staticmethod
    def _parse_quoted_value(line: str) -> str:
        """Parse the value off a ``KEY value`` line, handling REAPER's four
        quote styles (``"…"``, ``'…'``, `` `…` ``, or unquoted).

        REAPER picks whichever quote char doesn't appear in the value, so the
        reader needs to recognise each. An unterminated quote falls back to
        the remainder of the line.
        """
        parts = line.split(None, 1)
        if len(parts) < 2:
            return ""
        rest = parts[1].lstrip()
        if not rest:
            return ""
        quote = rest[0]
        if quote in _QUOTE_CHARS:
            end = rest.find(quote, 1)
            return rest[1:end] if end > 0 else rest[1:]
        return rest

    @classmethod
    def _parse_name(cls, line: str) -> str:
        return cls._parse_quoted_value(line)

    @staticmethod
    def _parse_vst_line(line: str) -> dict:
        # Layout: ``<VST "name" path/dll IDs…`` — name uses one of the quote
        # styles. Read from the first non-space char after ``<VST``.
        rest = line[4:].lstrip() if line.startswith("<VST") else line
        fx_name = "Unknown"
        if rest and rest[0] in _QUOTE_CHARS:
            quote = rest[0]
            end = rest.find(quote, 1)
            if end > 0:
                fx_name = rest[1:end]
        return {"name": fx_name, "encoded_data": [], "bypassed": False}

    @staticmethod
    def _looks_like_base64(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        # Real base64 lines contain ``+``, ``/``, ``=`` — the previous
        # ``str.isalnum()`` filter rejected those, dropping most data lines.
        return all(c in _BASE64_CHARS for c in stripped)

    @staticmethod
    def _parse_bypass(line: str) -> bool:
        parts = line.split()
        return bool(int(parts[1]))

    @staticmethod
    def _parse_volpan(line: str) -> tuple[float, float]:
        parts = line.split()
        if len(parts) >= 3:
            return float(parts[1]), float(parts[2])
        return 1.0, 0.0

    @staticmethod
    def _parse_mutesolo(line: str) -> tuple[bool, bool]:
        parts = line.split()
        if len(parts) >= 3:
            return bool(int(parts[1])), bool(int(parts[2]))
        return False, False

    def _create_fx(self, fx_dict: dict) -> FX:
        encoded_data = "".join(fx_dict["encoded_data"])
        if len(encoded_data) > self.MAX_ENCODED_DATA_LENGTH:
            encoded_data = f"<DATA_TRUNCATED: Original size {len(encoded_data)} bytes>"
        return FX(
            name=fx_dict["name"],
            encoded_param=encoded_data,
            bypassed=fx_dict["bypassed"],
        )

    @staticmethod
    def _parse_position(line: str) -> float:
        parts = line.split()
        if len(parts) >= 2:
            return float(parts[1])
        return 0.0

    @staticmethod
    def _parse_length(line: str) -> float:
        parts = line.split()
        if len(parts) >= 2:
            return float(parts[1])
        return 0.0

    def _parse_file_path(self, line: str) -> str:
        path = self._parse_quoted_value(line)
        if path and not os.path.isabs(path):
            base_dir = os.path.dirname(self.file_path)
            path = os.path.abspath(os.path.join(base_dir, path))
        return path

    @staticmethod
    def _create_audio_item(item_dict: dict) -> AudioItem:
        return AudioItem(
            position=item_dict["position"],
            length=item_dict["length"],
            audio_filepath=item_dict["audio_filepath"],
        )

    @staticmethod
    def _create_track_from_dict(track_dict: dict) -> Track:
        return Track(
            name=track_dict["name"],
            volume=track_dict["volume"],
            pan=track_dict["pan"],
            mute=track_dict["mute"],
            solo=track_dict["solo"],
            type=track_dict["type"],
            input_source=track_dict.get("input_source", ""),
            audio_filepath=track_dict.get("audio_filepath", ""),
            fx_chain=track_dict["fx_chain"],
            automation=track_dict["automation"],
            peak_level=track_dict["peak_level"],
            send_levels=track_dict["send_levels"],
            items=track_dict.get("items", []),
        )
