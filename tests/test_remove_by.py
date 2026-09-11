"""Parser tests for the remove-by column, run without Home Assistant."""
import sys, types, csv, io, logging
from datetime import datetime, timedelta, timezone

# Stub just enough of HA for coordinator.py to import.
ZONE = timezone(timedelta(hours=-4))  # America/New_York in September
def _mk(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m
_mk("aiohttp", ClientError=Exception, ClientTimeout=lambda **k: None)
ha = _mk("homeassistant")
dtu = _mk("homeassistant.util.dt", DEFAULT_TIME_ZONE=ZONE,
          now=lambda: NOW[0], utcnow=lambda: datetime.now(timezone.utc))
_mk("homeassistant.util", dt=dtu, slugify=lambda s: "".join(
    c if c.isalnum() else "_" for c in s.strip().lower()).strip("_"))
_mk("homeassistant.core", HomeAssistant=object)
_mk("homeassistant.helpers")
_mk("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda h: None)
class _DUC:
    def __init__(self, *a, **k): pass
    def __class_getitem__(cls, item): return cls
_mk("homeassistant.helpers.update_coordinator", DataUpdateCoordinator=_DUC,
    UpdateFailed=type("UpdateFailed", (Exception,), {}))
_mk("homeassistant.const", Platform=types.SimpleNamespace(SENSOR="sensor", BUTTON="button"))
import homeassistant.util as _hu
sys.modules["homeassistant"].util = _hu

NOW = [datetime(2026, 9, 11, 3, 0, tzinfo=ZONE)]
# Load coordinator.py on its own - importing the package would pull in
# __init__.py, which needs far more of Home Assistant than this needs.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "shul_zmanim.coordinator",
    "/home/user/custom-zmanim-ha-dashboard/custom_components/shul_zmanim/coordinator.py")
_const = importlib.util.spec_from_file_location(
    "shul_zmanim.const",
    "/home/user/custom-zmanim-ha-dashboard/custom_components/shul_zmanim/const.py")
_cm = importlib.util.module_from_spec(_const)
_const.loader.exec_module(_cm)
sys.modules["shul_zmanim"] = types.ModuleType("shul_zmanim")
sys.modules["shul_zmanim"].__path__ = []
sys.modules["shul_zmanim.const"] = _cm
_mod = importlib.util.module_from_spec(_spec)
sys.modules["shul_zmanim.coordinator"] = _mod
_spec.loader.exec_module(_mod)
parse_zmanim_csv = _mod.parse_zmanim_csv
parse_remove_by = _mod.parse_remove_by
find_remove_by_column = _mod.find_remove_by_column

logging.disable(logging.WARNING)
P=F=0
def check(name, cond, extra=""):
    global P, F
    if cond: P += 1; print("  PASS", name)
    else: F += 1; print("  FAIL", name, extra)

SHEET = """Key,Day,Zman,Time,Notes,WeekTitle,remove by
skver_a,Day One,התרת נדרים,3:15 PM,בערך 4:05,,09/14/26 11:00 PM
skver_b,Day One,הדלקת נרות,6:46 PM,,,09/14/26 11:00 PM
skver_c,Day One,מנחה,8:05 PM,note,,09/10/26 11:00 PM
skver_d,Day Two,שחרית,8:30 AM,,,
"""

print("== header matching ==")
for h in ["remove by", "Remove By", "RemoveBy", "remove_by", "REMOVE  BY"]:
    check(f"matches {h!r}", find_remove_by_column(["Day", h]) == h)
check("ignores unrelated headers", find_remove_by_column(["Day", "Notes"]) is None)

print("\n== value parsing ==")
check("sheet's own format", parse_remove_by("09/14/26 11:00 PM")
      == datetime(2026, 9, 14, 23, 0, tzinfo=ZONE))
check("four-digit year", parse_remove_by("09/14/2026 11:00 PM")
      == datetime(2026, 9, 14, 23, 0, tzinfo=ZONE))
check("24-hour", parse_remove_by("09/14/26 23:00")
      == datetime(2026, 9, 14, 23, 0, tzinfo=ZONE))
check("iso", parse_remove_by("2026-09-14 23:00")
      == datetime(2026, 9, 14, 23, 0, tzinfo=ZONE))
check("bare date means end of that day", parse_remove_by("09/14/26")
      == datetime(2026, 9, 15, 0, 0, tzinfo=ZONE))
check("empty cell never expires", parse_remove_by("") is None)
check("whitespace-only never expires", parse_remove_by("   ") is None)
# A typo must not silently delete a row.
check("unreadable value keeps the row", parse_remove_by("next week") is None)

print("\n== dropping expired rows ==")
d = parse_zmanim_csv(SHEET)
keys = [z["key"] for day in d["days"] for z in day["zmanim"]]
check("the past row is gone", "skver_c" not in keys, keys)
check("future rows stay", {"skver_a", "skver_b"} <= set(keys), keys)
check("a blank remove-by stays", "skver_d" in keys, keys)
check("row_count counts what is published", d["row_count"] == 3, d["row_count"])
check("expired rows are counted", d["expired_count"] == 1, d["expired_count"])
check("expired row has no item sensor", "skver_c" not in d["items"])
check("remove_by is published", d["items"]["skver_a"]["remove_by"]
      == "2026-09-14T23:00:00-04:00", d["items"]["skver_a"]["remove_by"])
check("blank remove_by publishes empty", d["items"]["skver_d"]["remove_by"] == "")
check("an emptied day disappears",
      [x["day_label"] for x in d["days"]] == ["Day One", "Day Two"],
      [x["day_label"] for x in d["days"]])

print("\n== the boundary ==")
AT = datetime(2026, 9, 14, 23, 0, tzinfo=ZONE)
check("gone at the stroke of the hour",
      "skver_a" not in parse_zmanim_csv(SHEET, now=AT)["items"])
check("still there a second before",
      "skver_a" in parse_zmanim_csv(SHEET, now=AT - timedelta(seconds=1))["items"])

print("\n== a sheet with no remove-by column at all ==")
OLD = "Key,Day,Zman,Time,Notes\nskver_a,Day One,שחרית,8:30 AM,\n"
d2 = parse_zmanim_csv(OLD)
check("parses unchanged", d2["row_count"] == 1 and "skver_a" in d2["items"])
check("nothing expires", d2["expired_count"] == 0)

print("\n== everything expired ==")
ALL = "Key,Day,Zman,Time,Notes,remove by\nskver_a,Day One,שחרית,8:30 AM,,09/01/26 11:00 PM\n"
d3 = parse_zmanim_csv(ALL)
check("days empty rather than broken", d3["days"] == [] and d3["row_count"] == 0)
check("still a valid payload", d3["expired_count"] == 1 and d3["items"] == {})

print(f"\n{P} passed, {F} failed")
sys.exit(1 if F else 0)
