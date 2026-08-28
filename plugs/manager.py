import os
from collections import defaultdict

from plugs.plug import Plug


class PlugManager:
    """Manager for noether plugs, declared via the NOETHER_PLUGS env var."""

    def __init__(self, plugs: list[Plug] | None = None):
        self.plugs: list[Plug] = list(plugs or [])
        env_plugs = os.getenv("NOETHER_PLUGS", "")
        for name in env_plugs.split(","):
            name = name.strip()
            if name:
                self.add_plug(Plug(name=name, package_name=name))

    def add_plug(self, plug: Plug) -> None:
        if not isinstance(plug, Plug):
            msg = "plug must be an instance of Plug"
            raise ValueError(msg)
        self.plugs.append(plug)

    def get_apps(self) -> list[str]:
        return [plug.name for plug in self.plugs]

    def get_config(self) -> defaultdict[str, dict]:
        configs: defaultdict[str, dict] = defaultdict(dict)
        for plug in self.plugs:
            for key, value in plug.configs.items():
                configs[plug.name][key] = value
        return configs
