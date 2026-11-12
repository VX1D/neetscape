"""German boards. Importing this package registers them (country "de", derived from the module path)."""
from . import arbeitnow, bundesagentur

__all__ = ["arbeitnow", "bundesagentur"]  # imported to register them
