"""Constants for the Shul Zmanim integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "shul_zmanim"

CONF_SHEET_URL = "sheet_url"
CONF_NAME = "name"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_NAME = "Shul Zmanim"
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 5

REQUIRED_COLUMNS = ("Day", "Zman", "Time")

# Optional column naming a moment after which the row should stop being
# published. Matched case- and separator-insensitively, so "remove by",
# "Remove By" and "remove_by" are all the same column.
REMOVE_BY_COLUMN = "removeby"

# Formats accepted in that column. A sheet cell is whatever the person
# typing it felt like, so take the shapes Google Sheets itself produces
# for a date-time, plus a bare date (which means the end of that day).
REMOVE_BY_FORMATS = (
    "%m/%d/%y %I:%M %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%y %H:%M",
    "%m/%d/%Y %H:%M",
    "%Y-%m-%d %I:%M %p",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
)

REMOVE_BY_DATE_FORMATS = (
    "%m/%d/%y",
    "%m/%d/%Y",
    "%Y-%m-%d",
)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

CARD_URL_BASE = f"/{DOMAIN}/frontend"
CARD_FILENAME = "shul-zmanim-card.js"

ATTR_SIZE_WARNING_BYTES = 8192
