"""Constants for the Luba Scheduler integration (no Home Assistant imports)."""
DOMAIN = "luba"
STORAGE_VERSION = 1
TITLE = "Luba Scheduler"
MAMMOTION = "mammotion"

GROUPS = ("A", "B")

# entry.options — mower (every Mammotion entity is stored by entity-registry
# entry id, never entity_id: the integration re-slugs, spike 2026-09-28 §1)
CONF_DEVICE = "mower_device"
CONF_ROLES = "mower_roles"            # {role: registry entry id}
CONF_ZONES = "zones"                  # {"A": [binding], "B": [binding]}

# binding = {"id": registry entry id, "unique_id", "hash", "name"} — only "id"
# resolves; the rest is a fingerprint for diagnostics and repair messages.
BIND_ID = "id"
BIND_UID = "unique_id"
BIND_HASH = "hash"
BIND_NAME = "name"

# Mower roles derived from the device: role -> (domain, unique_id key)
ROLE_MOWER = "lawn_mower"
ROLE_ACTIVITY = "activity_mode"
ROLE_BATTERY = "battery"
ROLE_PROGRESS = "progress"
ROLE_CHARGING = "charging"
ROLE_CAMERA = "camera_brightness"
ROLE_RTK_FIX = "rtk_fix"
ROLE_WORK_AREA = "work_area"
MOWER_ROLES: dict[str, tuple[str, str]] = {
    ROLE_MOWER: ("lawn_mower", "mower"),
    ROLE_ACTIVITY: ("sensor", "activity_mode"),
    ROLE_BATTERY: ("sensor", "battery_percent"),
    ROLE_PROGRESS: ("sensor", "progress"),
    ROLE_CHARGING: ("binary_sensor", "charging"),
    ROLE_CAMERA: ("sensor", "camera_brightness"),
    # positioning_mode is RTKStatus (fix quality: Fix/Float/Single);
    # position_mode is the datalink and must never be used here.
    ROLE_RTK_FIX: ("sensor", "positioning_mode"),
    ROLE_WORK_AREA: ("sensor", "work_area"),
}
AREA_TRANSLATION_KEY = "area"
TASK_AREA_SUFFIX = "_task_area"

# entry.options — external inputs (not Mammotion; stored as entity_id)
CONF_SEASON = "season_entity"
CONF_WEATHER = "weather_entity"
CONF_PRECIP_TYPE = "precip_type_entity"
CONF_PRECIP_CHANCE = "precip_chance_entity"
CONF_CANOPY = "canopy_temp_entity"
CONF_LIGHTNING_DISTANCE = "lightning_distance_entity"
CONF_LIGHTNING_STRIKE = "lightning_strike_entity"
CONF_DRY = {"A": "dry_grass_a_entity", "B": "dry_grass_b_entity"}
CONF_MOW_ALLOWED = {"A": "mow_allowed_a_entity", "B": "mow_allowed_b_entity"}
CONF_CALENDAR = "calendar_entity"
CONF_NOTIFY = "notify_service"
CONF_GATE = "gate_entity"
CONF_GATE_POLARITY = "gate_polarity"
GATE_ON_CLOSED = "on_closed"
GATE_ON_OPEN = "on_open"

# entry.options — tuning (all ints/floats, typed at entry by the options schema)
CONF_CUTOFF_MIN = "cutoff_before_sunset_minutes"
CONF_CANOPY_MIN = "canopy_min_f"
CONF_CANOPY_MAX = "canopy_max_f"
CONF_PRECIP_MAX = "precip_chance_max"
CONF_LIGHTNING_RADIUS = "lightning_radius"
CONF_LIGHTNING_RECENCY = "lightning_recency_minutes"
CONF_START_FLOOR = "fresh_start_battery_floor"
CONF_OPTIMAL_DELAY = "optimal_delay_minutes"
CONF_ANGLES = "angle_options"
CONF_SPACINGS = "spacing_options"

DEFAULTS = {
    CONF_GATE_POLARITY: GATE_ON_CLOSED,
    CONF_CUTOFF_MIN: 60,
    CONF_CANOPY_MIN: 50,
    CONF_CANOPY_MAX: 90,
    CONF_PRECIP_MAX: 51,
    CONF_LIGHTNING_RADIUS: 5,
    CONF_LIGHTNING_RECENCY: 5,
    CONF_START_FLOOR: 95,
    CONF_OPTIMAL_DELAY: 5,
    CONF_ANGLES: [12, 48, 24, 60, 36],
    CONF_SPACINGS: [28, 29, 31, 33, 34],
}

CUTS_PER_GROUP_OPTIONS = [1, 2, 3]
HEIGHT_MIN_MM, HEIGHT_MAX_MM = 15, 100     # mammotion.start_mow's blade_height range
