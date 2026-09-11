"""Data update coordinator for the Shul Zmanim integration."""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta
from typing import Any

import aiohttp
import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .const import (
    ATTR_SIZE_WARNING_BYTES,
    DOMAIN,
    REMOVE_BY_COLUMN,
    REMOVE_BY_DATE_FORMATS,
    REMOVE_BY_FORMATS,
    REQUIRED_COLUMNS,
)

_LOGGER = logging.getLogger(__name__)


def _normalize_header(name: str) -> str:
    """Fold a header to letters only, so spacing and case stop mattering."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def find_remove_by_column(fieldnames: list[str] | None) -> str | None:
    """Return the sheet's remove-by header as written, if it has one."""
    for name in fieldnames or []:
        if name and _normalize_header(name) == REMOVE_BY_COLUMN:
            return name
    return None


def parse_remove_by(value: str) -> datetime | None:
    """Parse a remove-by cell into a local-time datetime.

    Returns None for an empty cell (the row simply never expires) and for
    one that cannot be read - a typo must not make a row vanish, which is
    the same call the rest of this parser makes about bad input.
    """
    value = (value or "").strip()
    if not value:
        return None

    local = dt_util.DEFAULT_TIME_ZONE

    for fmt in REMOVE_BY_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=local)
        except ValueError:
            continue

    # A bare date means the end of that day, not midnight at its start -
    # "remove by the 14th" reads as "the 14th is its last day".
    for fmt in REMOVE_BY_DATE_FORMATS:
        try:
            day = datetime.strptime(value, fmt)
        except ValueError:
            continue
        return (day + timedelta(days=1)).replace(tzinfo=local)

    _LOGGER.warning(
        "Could not read remove-by value %r; keeping the row", value
    )
    return None


def parse_zmanim_csv(
    csv_text: str, now: datetime | None = None
) -> dict[str, Any]:
    """Parse the sheet's CSV export into a day-grouped structure.

    Day and zman order both follow the order rows appear in the sheet -
    no separate numeric order columns needed. Individual malformed rows
    are skipped (and logged) rather than failing the whole parse, so a
    single typo doesn't blank the dashboard.

    A row whose optional remove-by column has passed is dropped here, at
    the source, rather than left for each consumer to filter: it then
    disappears exactly the way a row deleted from the sheet does, and
    every card, template and automation gets that for free.
    """
    now = now or dt_util.now()

    reader = csv.DictReader(io.StringIO(csv_text))

    if not reader.fieldnames:
        raise ValueError("empty_sheet")

    remove_by_column = find_remove_by_column(reader.fieldnames)

    expired_count = 0

    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise ValueError(f"missing_columns: {', '.join(missing)}")

    days: dict[str, dict[str, Any]] = {}
    # Flat map of individually-addressable zmanim, keyed by the optional `Key`
    # column (slugified). Powers the per-item `sensor.shul_zmanim_<key>` sensors.
    items: dict[str, dict[str, Any]] = {}
    week_title = ""
    row_count = 0

    for index, row in enumerate(reader):
        week_title_cell = (row.get("WeekTitle") or "").strip()
        if week_title_cell and not week_title:
            week_title = week_title_cell

        day_label = (row.get("Day") or "").strip()
        zman_name = (row.get("Zman") or "").strip()
        if not day_label or not zman_name:
            _LOGGER.warning("Skipping row %s: missing Day or Zman", index)
            continue

        remove_by = (
            parse_remove_by(row.get(remove_by_column, ""))
            if remove_by_column
            else None
        )

        if remove_by is not None and remove_by <= now:
            expired_count += 1
            continue

        # Optional stable key -> its own sensor. Slugified so it is a valid
        # entity-id suffix; a Hebrew/empty key slugifies away and is ignored.
        key = slugify((row.get("Key") or "").strip())

        zman = {
            "name": zman_name,
            "time": (row.get("Time") or "").strip(),
            "notes": (row.get("Notes") or "").strip(),
            # Optional per-row icon override (an mdi name like "mdi:candle").
            # Blank is fine - the card auto-picks an icon from the name.
            "icon": (row.get("Icon") or "").strip(),
            "key": key,
            # Published so a consumer can show "until ..." if it wants to;
            # nothing needs to act on it, the row is already gone by then.
            "remove_by": remove_by.isoformat() if remove_by else "",
        }

        day = days.setdefault(
            day_label,
            {
                "day_order": index,
                "day_label": day_label,
                "zmanim": [],
            },
        )
        day["zmanim"].append(zman)
        row_count += 1

        if key:
            if key in items:
                _LOGGER.warning("Skipping duplicate Key '%s' on row %s", key, index)
            else:
                items[key] = {**zman, "day_label": day_label}

    sorted_days = sorted(days.values(), key=lambda d: d["day_order"])

    if expired_count:
        _LOGGER.debug("Dropped %s row(s) past their remove-by", expired_count)

    return {
        "week_title": week_title,
        "days": sorted_days,
        "items": items,
        "row_count": row_count,
        "expired_count": expired_count,
        "last_updated": dt_util.utcnow().isoformat(),
    }


class ShulZmanimCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches and parses the zmanim Google Sheet on a schedule."""

    def __init__(self, hass: HomeAssistant, csv_url: str, update_interval_minutes: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )
        self._csv_url = csv_url

    async def _async_update_data(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                self._csv_url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                text = await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise UpdateFailed(f"Error fetching zmanim sheet: {err}") from err

        if len(text.encode("utf-8")) > ATTR_SIZE_WARNING_BYTES:
            _LOGGER.warning(
                "Zmanim sheet response is larger than expected (%d bytes)",
                len(text.encode("utf-8")),
            )

        try:
            return parse_zmanim_csv(text)
        except ValueError as err:
            raise UpdateFailed(f"Error parsing zmanim sheet: {err}") from err
