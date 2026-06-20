"""Read REAPER's plugin cache files to enumerate installed plugins (vendored from dschuler36)."""

import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class InstalledPlugin:
    name: str
    plugin_type: str  # VST2, VST3, AU, JS, CLAP
    path: str
    manufacturer: str | None = None
    category: str | None = None


class FXFinder:
    """Find installed REAPER plugins by parsing the resource directory's INI cache files."""

    def __init__(self, reaper_resource_path: str | None = None):
        if reaper_resource_path:
            self.reaper_path = Path(reaper_resource_path)
        else:
            mac_path = Path.home() / "Library" / "Application Support" / "REAPER"
            linux_path = Path.home() / ".config" / "REAPER"
            windows_path = Path(os.environ.get("APPDATA", "")) / "REAPER"
            if mac_path.exists():
                self.reaper_path = mac_path
            elif linux_path.exists():
                self.reaper_path = linux_path
            elif windows_path.exists():
                self.reaper_path = windows_path
            else:
                self.reaper_path = mac_path

    def find_installed_plugins(self) -> list[dict]:
        plugins: list[dict] = []
        plugins.extend(self._parse_vst_plugins())
        plugins.extend(self._parse_au_plugins())
        plugins.extend(self._parse_js_plugins())
        plugins.extend(self._parse_clap_plugins())
        return plugins

    def get_plugins_by_type(self, plugin_type: str) -> list[dict]:
        return [
            p
            for p in self.find_installed_plugins()
            if p["plugin_type"].upper() == plugin_type.upper()
        ]

    def search_plugins(self, query: str) -> list[dict]:
        q = query.lower()
        return [
            p
            for p in self.find_installed_plugins()
            if q in p["name"].lower()
            or (p.get("manufacturer") and q in p["manufacturer"].lower())
            or q in p["plugin_type"].lower()
        ]

    def _parse_vst_plugins(self) -> list[dict]:
        plugins: list[dict] = []
        vst_files = [
            self.reaper_path / "reaper-vstplugins_arm64.ini",
            self.reaper_path / "reaper-vstplugins64.ini",
            self.reaper_path / "reaper-vstplugins.ini",
        ]
        for vst_file in vst_files:
            if not vst_file.exists():
                continue
            try:
                with open(vst_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith(";") or line.startswith("["):
                            continue
                        if "=" in line:
                            filename, info = line.split("=", 1)
                            filename = filename.strip()
                            info = info.strip()
                            plugin_type = "VST3" if filename.endswith(".vst3") else "VST2"
                            parts = info.split(",", 2)
                            if len(parts) >= 3:
                                display = parts[2].replace("!!!VSTi", "").strip()
                                name, manufacturer = self._parse_vst_display_name(display)
                                plugins.append(
                                    asdict(
                                        InstalledPlugin(
                                            name=name,
                                            plugin_type=plugin_type,
                                            path=filename,
                                            manufacturer=manufacturer,
                                        )
                                    )
                                )
            except Exception as e:
                print(f"Error parsing {vst_file}: {e}")
        return plugins

    @staticmethod
    def _parse_vst_display_name(display_info: str) -> tuple[str, str | None]:
        # REAPER's VST display is "Name (Manufacturer)" with the manufacturer
        # in the *last* parenthesized group — so "Soothe2 (FF Pro) (oeksound)"
        # → name="Soothe2 (FF Pro)", manufacturer="oeksound", not the other
        # way around (which is what a left-split would produce).
        s = display_info.strip()
        open_paren = s.rfind("(")
        close_paren = s.rfind(")")
        if 0 < open_paren < close_paren:
            name = s[:open_paren].strip()
            manufacturer = s[open_paren + 1 : close_paren].strip()
            return name or s, manufacturer or None
        return s, None

    def _parse_au_plugins(self) -> list[dict]:
        plugins: list[dict] = []
        au_files = [
            self.reaper_path / "reaper-auplugins_arm64.ini",
            self.reaper_path / "reaper-auplugins64.ini",
            self.reaper_path / "reaper-auplugins.ini",
        ]
        for au_file in au_files:
            if not au_file.exists():
                continue
            try:
                with open(au_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith(";") or line.startswith("["):
                            continue
                        if "=" in line:
                            name_part, info = line.split("=", 1)
                            name_part = name_part.strip()
                            if info.strip() == "<!inst>":
                                continue
                            manufacturer, name = self._parse_au_name(name_part)
                            plugins.append(
                                asdict(
                                    InstalledPlugin(
                                        name=name,
                                        plugin_type="AU",
                                        path=f"AU:{name_part}",
                                        manufacturer=manufacturer,
                                    )
                                )
                            )
            except Exception as e:
                print(f"Error parsing {au_file}: {e}")
        return plugins

    @staticmethod
    def _parse_au_name(name_part: str) -> tuple[str | None, str]:
        if ":" in name_part:
            parts = name_part.split(":", 1)
            return parts[0].strip(), parts[1].strip()
        return None, name_part

    def _parse_js_plugins(self) -> list[dict]:
        plugins: list[dict] = []
        js_file = self.reaper_path / "reaper-jsfx.ini"
        if not js_file.exists():
            return plugins
        try:
            with open(js_file, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(";") or line.startswith("["):
                        continue
                    if "=" in line:
                        name_part, path = line.split("=", 1)
                        name_part = name_part.strip()
                        path = path.strip()
                        category = None
                        if "/" in name_part:
                            parts = name_part.split("/")
                            category = parts[0]
                            name = "/".join(parts[1:])
                        else:
                            name = name_part
                        plugins.append(
                            asdict(
                                InstalledPlugin(
                                    name=name,
                                    plugin_type="JS",
                                    path=path,
                                    manufacturer="JSFX",
                                    category=category,
                                )
                            )
                        )
        except Exception as e:
            print(f"Error parsing {js_file}: {e}")
        return plugins

    def _parse_clap_plugins(self) -> list[dict]:
        plugins: list[dict] = []
        clap_files = [
            self.reaper_path / "reaper-clapplugins64.ini",
            self.reaper_path / "reaper-clapplugins.ini",
        ]
        for clap_file in clap_files:
            if not clap_file.exists():
                continue
            try:
                with open(clap_file, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith(";"):
                            continue
                        if "=" in line:
                            name, path = line.split("=", 1)
                            name = name.strip().strip('"')
                            path = path.strip().strip('"')
                            plugins.append(
                                asdict(
                                    InstalledPlugin(
                                        name=name,
                                        plugin_type="CLAP",
                                        path=path,
                                        manufacturer=self._extract_manufacturer(name, path),
                                    )
                                )
                            )
            except Exception as e:
                print(f"Error parsing {clap_file}: {e}")
        return plugins

    @staticmethod
    def _extract_manufacturer(name: str, path: str) -> str | None:
        for separator in [" - ", ": ", " : "]:
            if separator in name:
                return name.split(separator)[0].strip()
        # Walk the path looking for the first segment that doesn't look like
        # a generic plugin host directory. macOS uses "Plug-Ins" (hyphenated),
        # and CLAP needs to be on the skip list too — without these, a path
        # like ``/Library/Audio/Plug-Ins/CLAP/X.clap`` falls through to the
        # filesystem-root ``/`` segment.
        skip = {
            "/",
            "VST",
            "VST3",
            "VST2",
            "AU",
            "CLAP",
            "Plugins",
            "Plug-Ins",
            "Audio",
            "Components",
            "Library",
            "Application Support",
            "REAPER",
        }
        for part in Path(path).parts:
            if part in skip:
                continue
            # Skip drive roots like "C:\" on Windows and any single-char
            # segment that's just punctuation.
            if len(part) <= 1 or part.endswith(":"):
                continue
            return part
        return None
