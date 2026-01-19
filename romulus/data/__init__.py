"""Data management module for ROMULUS."""

from romulus.data.ingestion import fetch_daily_data
from romulus.data.universe import Universe

__all__ = ["Universe", "fetch_daily_data"]
