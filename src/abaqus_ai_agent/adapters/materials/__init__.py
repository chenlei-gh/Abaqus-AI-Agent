"""Material database adapters for external knowledge grounding."""

from .campus import CampusAdapter
from .manufacturer import ManufacturerAdapter

__all__ = ["CampusAdapter", "ManufacturerAdapter"]
