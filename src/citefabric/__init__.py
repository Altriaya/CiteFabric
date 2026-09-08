"""CiteFabric's public asynchronous Python API."""

__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "CiteFabricClient":
        from .client import CiteFabricClient

        return CiteFabricClient
    if name == "Config":
        from .config import Config

        return Config
    raise AttributeError(name)


__all__ = ["CiteFabricClient", "Config", "__version__"]
