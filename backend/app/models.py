"""Single schema source. Mirrors docs/DATA_MODEL.md §3 — change both together."""
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, SmallInteger, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def E(*values: str) -> Enum:
    """Enum stored as VARCHAR + CHECK (migration friendly)."""
    return Enum(*values, native_enum=False, create_constraint=True, length=40, validate_strings=True)


SOURCE = E("PUBLIC", "SYNTHETIC", "LIVE")
STATUS_SITE = E("OPERATIONAL", "DEGRADED", "MAINTENANCE", "OFFLINE")
MISSION_TYPES = ("TRAINING", "AIR_DEFENCE_PATROL", "QRA_SCRAMBLE", "INTERCEPT", "STRIKE_EXERCISE", "CAS_EXERCISE",
                 "RECCE_ISR", "AIRLIFT", "PARA_DROP", "CASEVAC", "HADR", "AAR_SUPPORT", "AEW_SUPPORT", "FERRY",
                 "FUNCTIONAL_CHECK", "SAR")
AIRCRAFT_STATUS = ("AVAILABLE", "STANDBY", "QRA", "AIRBORNE", "TURNAROUND", "MAINT_SCHEDULED",
                   "MAINT_UNSCHEDULED", "AOG", "DEPOT", "RETIRED")
DUTY_STATUS = ("ON_DUTY", "STANDBY", "QRA", "BRIEFED", "AIRBORNE", "CREW_REST", "OFF_DUTY", "LEAVE", "SICK", "COURSE")
SORTIE_STATUS = ("PLANNED", "CREWED", "READY", "AIRBORNE", "ON_STATION", "RTB", "LANDED", "COMPLETED",
                 "CANCELLED", "ABORTED")
ACTIVE_SORTIE = ("CREWED", "READY", "AIRBORNE", "ON_STATION", "RTB")
MISSION_STATUS = ("REQUESTED", "APPROVED", "PLANNED", "TASKED", "ACTIVE", "COMPLETED", "CANCELLED", "SPLIT")


class Base(DeclarativeBase):
    pass


class Common:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    source: Mapped[str] = mapped_column(SOURCE, default="SYNTHETIC", server_default="SYNTHETIC", nullable=False)
    source_ref: Mapped[str | None] = mapped_column(Text)


def fk(table: str, nullable: bool = False, index: bool = True):
    return mapped_column(BigInteger, ForeignKey(f"{table}.id"), nullable=nullable, index=index)


# ---------------------------------------------------------------- A. organisation & geography
class Command(Common, Base):
    __tablename__ = "command"
    code: Mapped[str] = mapped_column(E("WAC", "SWAC", "CAC", "EAC", "SAC", "TC", "MC"), unique=True)
    name: Mapped[str] = mapped_column(Text)
    hq_name: Mapped[str] = mapped_column(Text)
    hq_geom = mapped_column(Geometry("POINT", srid=4326))
    is_operational: Mapped[bool] = mapped_column(Boolean, default=True)


class AirBase(Common, Base):
    __tablename__ = "base"
    code: Mapped[str] = mapped_column(String(16), unique=True)
    iata: Mapped[str | None] = mapped_column(String(4))
    name: Mapped[str] = mapped_column(Text)
    alt_names: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    country_iso3: Mapped[str] = mapped_column(String(3))
    side: Mapped[str] = mapped_column(E("OWN", "OTHER_INDIAN_MIL", "FOREIGN"), index=True)
    operator: Mapped[str] = mapped_column(E("IAF", "IN", "IA_AVN", "ICG", "PAF", "PLAAF", "PLANAF", "BAF", "SLAF",
                                            "MAF", "NA_AVN", "AAF", "CIVIL_JOINT", "OTHER"))
    base_type: Mapped[str] = mapped_column(E("AIR_FORCE_STATION", "FBSU", "ALG", "JOINT_USE",
                                             "TRAINING_ESTABLISHMENT", "BASE_REPAIR_DEPOT", "HELIBASE", "LOGISTICS",
                                             "RADAR_STATION", "FOREIGN_MILITARY", "FOREIGN_JOINT_USE",
                                             "OTHER_INDIAN_MIL"))
    command_id: Mapped[int | None] = fk("command", nullable=True)
    wing: Mapped[str | None] = mapped_column(Text)
    role_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    ops_status: Mapped[str] = mapped_column(E("OPERATIONAL", "LIMITED", "CLOSED"), default="OPERATIONAL")
    affiliation: Mapped[str] = mapped_column(E("FRIEND", "HOSTILE", "NEUTRAL"), default="FRIEND")
    public_notes: Mapped[str | None] = mapped_column(Text)
    wikipedia_url: Mapped[str | None] = mapped_column(Text)
    ourairports_id: Mapped[str | None] = mapped_column(Text)
    metar_station: Mapped[str | None] = mapped_column(String(4))  # nearest METAR (own or ≤50 km)
    metar_station_km: Mapped[float | None] = mapped_column(Float)


class Runway(Common, Base):
    __tablename__ = "runway"
    base_id: Mapped[int] = fk("base")
    designator: Mapped[str] = mapped_column(Text)
    length_m: Mapped[float | None] = mapped_column(Float)
    width_m: Mapped[float | None] = mapped_column(Float)
    surface: Mapped[str] = mapped_column(E("ASPHALT", "CONCRETE", "GRAVEL", "GRASS", "MATTING", "UNKNOWN"),
                                         default="UNKNOWN")
    heading_true_deg: Mapped[float | None] = mapped_column(Float)
    lighted: Mapped[bool | None] = mapped_column(Boolean)
    geom = mapped_column(Geometry("LINESTRING", srid=4326))
    status: Mapped[str] = mapped_column(E("OPEN", "RESTRICTED", "CLOSED", "UNDER_REPAIR"), default="OPEN")


class ParkingFacility(Common, Base):
    __tablename__ = "parking_facility"
    base_id: Mapped[int] = fk("base")
    kind: Mapped[str] = mapped_column(E("HAS", "BLAST_PEN", "OPEN_APRON", "MAINT_HANGAR", "TRANSPORT_APRON",
                                        "HELIPAD", "UAV_HANGAR"))
    slot_size: Mapped[str] = mapped_column(E("S", "M", "L", "XL"))
    slots_total: Mapped[int] = mapped_column(Integer)
    slots_unserviceable: Mapped[int] = mapped_column(Integer, default=0)


class QraPosture(Common, Base):
    __tablename__ = "qra_posture"
    base_id: Mapped[int] = fk("base")
    aircraft_type_id: Mapped[int] = fk("aircraft_type")
    required_aircraft: Mapped[int] = mapped_column(Integer, default=2)
    readiness_min: Mapped[int] = mapped_column(Integer, default=5)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------- B. fleet
class AircraftType(Common, Base):
    __tablename__ = "aircraft_type"
    icao_type: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(Text, unique=True)
    variant: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(E("FIXED_WING", "ROTARY_WING", "UAV_FIXED_WING", "UAV_ROTARY_SMALL"))
    role: Mapped[str] = mapped_column(E(
        "FIGHTER_MULTIROLE", "AIR_SUPERIORITY", "STRIKE", "TRAINER_BASIC", "TRAINER_INTERMEDIATE",
        "TRAINER_ADVANCED", "TRANSPORT_STRATEGIC", "TRANSPORT_TACTICAL", "TRANSPORT_LIGHT", "VIP_TRANSPORT",
        "TANKER", "AEW_C", "ISR", "UTILITY_HELO", "ATTACK_HELO", "HEAVY_LIFT_HELO", "LIGHT_HELO", "UAV_MALE",
        "UAV_TACTICAL", "SMALL_UAS"))
    seats_pilot: Mapped[int] = mapped_column(Integer, default=1)
    seats_other: Mapped[int] = mapped_column(Integer, default=0)
    max_fuel_kg: Mapped[float] = mapped_column(Float)
    burn_kg_per_h: Mapped[float] = mapped_column(Float)
    cruise_kt: Mapped[float] = mapped_column(Float)
    endurance_h: Mapped[float] = mapped_column(Float)
    combat_radius_km: Mapped[float | None] = mapped_column(Float)
    slot_size: Mapped[str] = mapped_column(E("S", "M", "L", "XL"))
    maint_interval_h: Mapped[int] = mapped_column(Integer, default=100)
    turnaround_min: Mapped[int] = mapped_column(Integer, default=40)
    serial_prefix: Mapped[str] = mapped_column(String(4))
    sidc_function: Mapped[str | None] = mapped_column(String(10))
    in_service: Mapped[bool] = mapped_column(Boolean, default=True)


class Squadron(Common, Base):
    __tablename__ = "squadron"
    number: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    aircraft_type_id: Mapped[int] = fk("aircraft_type")
    home_base_id: Mapped[int] = fk("base")
    wing: Mapped[str | None] = mapped_column(Text)
    unit_establishment: Mapped[int] = mapped_column(Integer)


class Aircraft(Common, Base):
    __tablename__ = "aircraft"
    tail_no: Mapped[str] = mapped_column(String(16), unique=True)
    aircraft_type_id: Mapped[int] = fk("aircraft_type")
    squadron_id: Mapped[int] = fk("squadron")
    home_base_id: Mapped[int] = fk("base")
    current_base_id: Mapped[int | None] = fk("base", nullable=True)
    status: Mapped[str] = mapped_column(E(*AIRCRAFT_STATUS), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    readiness_min: Mapped[int | None] = mapped_column(Integer)
    airframe_hours: Mapped[float] = mapped_column(Float, default=0)
    hours_since_maint: Mapped[float] = mapped_column(Float, default=0)
    next_maint_due_hours: Mapped[float] = mapped_column(Float, default=100)
    next_maint_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maint_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fuel_kg: Mapped[float] = mapped_column(Float, default=0)
    induction_year: Mapped[int | None] = mapped_column(Integer)
    last_sortie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- C. people
class Aircrew(Common, Base):
    __tablename__ = "aircrew"
    service_no: Mapped[str] = mapped_column(String(24), unique=True)
    rank: Mapped[str] = mapped_column(E("FG_OFFR", "FLT_LT", "SQN_LDR", "WG_CDR", "GP_CAPT", "AIR_CMDE"))
    first_name: Mapped[str] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text)
    callsign: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date] = mapped_column(Date)
    commission_date: Mapped[date] = mapped_column(Date)
    aircrew_role: Mapped[str] = mapped_column(E("PILOT", "WSO", "NAVIGATOR", "FLIGHT_ENGINEER", "LOADMASTER",
                                                "FLIGHT_GUNNER", "RPA_PILOT", "PAYLOAD_OPERATOR"))
    stream: Mapped[str] = mapped_column(E("FIGHTER", "TRANSPORT", "HELICOPTER", "RPA"))
    squadron_id: Mapped[int | None] = fk("squadron", nullable=True)
    base_id: Mapped[int] = fk("base")
    appointment: Mapped[str | None] = mapped_column(Text)
    ops_category: Mapped[str] = mapped_column(E("UNDER_CONVERSION", "SEMI_OPERATIONAL", "FULLY_OPERATIONAL",
                                                "FLIGHT_LEAD", "INSTRUCTOR"))
    instrument_rating: Mapped[str] = mapped_column(E("WHITE", "GREEN", "MASTER_GREEN"))
    medical_status: Mapped[str] = mapped_column(E("FIT_FULL", "FIT_RESTRICTED", "TEMP_UNFIT", "GROUNDED"))
    medical_valid_until: Mapped[date] = mapped_column(Date)
    duty_status: Mapped[str] = mapped_column(E(*DUTY_STATUS), index=True)
    rest_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_hours: Mapped[float] = mapped_column(Float, default=0)
    night_hours: Mapped[float] = mapped_column(Float, default=0)
    instrument_hours: Mapped[float] = mapped_column(Float, default=0)


class AircrewTypeHours(Common, Base):
    __tablename__ = "aircrew_type_hours"
    __table_args__ = (UniqueConstraint("aircrew_id", "aircraft_type_id"),)
    aircrew_id: Mapped[int] = fk("aircrew")
    aircraft_type_id: Mapped[int] = fk("aircraft_type")
    hours: Mapped[float] = mapped_column(Float, default=0)
    captain_hours: Mapped[float] = mapped_column(Float, default=0)
    night_hours: Mapped[float] = mapped_column(Float, default=0)
    instrument_hours: Mapped[float] = mapped_column(Float, default=0)
    last_flown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AircrewQualification(Common, Base):
    __tablename__ = "aircrew_qualification"
    aircrew_id: Mapped[int] = fk("aircrew")
    code: Mapped[str] = mapped_column(E("QFI", "NIGHT", "NVG", "AAR_RECEIVER", "FORMATION_LEAD_2",
                                        "FORMATION_LEAD_4", "LOW_LEVEL", "MOUNTAIN_FLYING", "SAR", "PARA_DROP",
                                        "TEST_PILOT", "QRA_CLEARED"))
    aircraft_type_id: Mapped[int | None] = fk("aircraft_type", nullable=True)
    awarded_on: Mapped[date] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)


class AircrewPosting(Common, Base):
    __tablename__ = "aircrew_posting"
    aircrew_id: Mapped[int] = fk("aircrew")
    squadron_id: Mapped[int | None] = fk("squadron", nullable=True)
    base_id: Mapped[int | None] = fk("base", nullable=True)
    aircraft_type_id: Mapped[int | None] = fk("aircraft_type", nullable=True)
    appointment: Mapped[str | None] = mapped_column(Text)
    from_date: Mapped[date] = mapped_column(Date)
    to_date: Mapped[date | None] = mapped_column(Date)


class GroundCrewStrength(Common, Base):
    __tablename__ = "ground_crew_strength"
    base_id: Mapped[int] = fk("base")
    trade: Mapped[str] = mapped_column(E("AIRFRAME", "ENGINE", "AVIONICS", "ELECTRICAL", "ARMAMENT", "POL", "ATC",
                                         "MET", "MT", "FIRE_CRASH_RESCUE", "STORES", "MEDICAL", "SECURITY",
                                         "RADAR_TECH", "COMMS_TECH"))
    shift: Mapped[str] = mapped_column(E("A", "B", "C"))
    authorised: Mapped[int] = mapped_column(Integer)
    held: Mapped[int] = mapped_column(Integer)
    on_duty: Mapped[int] = mapped_column(Integer, default=0)
    standby: Mapped[int] = mapped_column(Integer, default=0)
    on_leave: Mapped[int] = mapped_column(Integer, default=0)


class DutyRosterEntry(Common, Base):
    __tablename__ = "duty_roster_entry"
    aircrew_id: Mapped[int] = fk("aircrew")
    base_id: Mapped[int] = fk("base")
    duty_type: Mapped[str] = mapped_column(E("FLYING", "STANDBY", "QRA", "OPS_DUTY", "REST", "LEAVE", "COURSE"))
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    readiness_min: Mapped[int | None] = mapped_column(Integer)


# ---------------------------------------------------------------- D. operations
class Mission(Common, Base):
    __tablename__ = "mission"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(Text)
    mission_type: Mapped[str] = mapped_column(E(*MISSION_TYPES))
    priority: Mapped[str] = mapped_column(E("P1", "P2", "P3", "P4"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    area_geom = mapped_column(Geometry("POLYGON", srid=4326))
    status: Mapped[str] = mapped_column(E(*MISSION_STATUS), index=True)
    requesting_command_id: Mapped[int | None] = fk("command", nullable=True)
    # Phase 2 tasking (PRD §17 FR-MSN). Geometry stays inside India and >= border_buffer_km from it (I8, I15).
    target_geom = mapped_column(Geometry("POINT", srid=4326))
    target_base_id: Mapped[int | None] = fk("base", nullable=True)          # airlift / CASEVAC destination
    required_aircraft: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    eligible_roles: Mapped[list[str] | None] = mapped_column(ARRAY(Text))   # aircraft_type.role values
    loadout_code: Mapped[str | None] = mapped_column(String(24))
    on_station_min: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    min_quals: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    max_risk: Mapped[str] = mapped_column(E("LOW", "MED", "HIGH"), default="MED", server_default="MED")
    notes: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(E("NONE", "PARTIAL", "MET", "MISSED"), default="NONE", server_default="NONE")
    on_station_achieved_min: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    # D41: needs this mission (an AEW&C orbit) on station for its whole time on station
    depends_on_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mission.id"), index=True)
    # D42: a part of a split mission (status SPLIT on the parent): RELIEF = one shift in time, BASES = a share of aircraft
    parent_mission_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("mission.id"), index=True)
    part_no: Mapped[int | None] = mapped_column(Integer)
    parts: Mapped[int | None] = mapped_column(Integer)
    split_kind: Mapped[str | None] = mapped_column(String(8))


class Sortie(Common, Base):
    __tablename__ = "sortie"
    code: Mapped[str] = mapped_column(String(32), unique=True)
    mission_id: Mapped[int | None] = fk("mission", nullable=True)
    origin: Mapped[str] = mapped_column(E("SIM_PROGRAMME", "HUMAN", "QRA_SCRAMBLE", "PLAN"))
    mission_type: Mapped[str] = mapped_column(E(*MISSION_TYPES))
    priority: Mapped[str] = mapped_column(E("P1", "P2", "P3", "P4"))
    departure_base_id: Mapped[int] = fk("base")
    recovery_base_id: Mapped[int] = fk("base")
    status: Mapped[str] = mapped_column(E(*SORTIE_STATUS), index=True)
    planned_launch_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actual_launch_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_recovery_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_recovery_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(E("WX", "AIRCRAFT_US", "CREW_UNAVAILABLE", "FUEL",
                                                        "TASKING_CHANGE", "USER_CANCELLED", "OTHER"))
    route_geom = mapped_column(Geometry("LINESTRING", srid=4326))
    orbit_geom = mapped_column(Geometry("POLYGON", srid=4326))
    cruise_alt_m: Mapped[float] = mapped_column(Float, default=6000)
    fuel_planned_kg: Mapped[float] = mapped_column(Float, default=0)
    fuel_used_kg: Mapped[float] = mapped_column(Float, default=0)
    target_track_id: Mapped[str | None] = mapped_column(Text)
    loadout_code: Mapped[str | None] = mapped_column(String(24))
    plan_item_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    reroute_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # in-flight re-role: new route starts here


class SortieAircraft(Common, Base):
    __tablename__ = "sortie_aircraft"
    sortie_id: Mapped[int] = fk("sortie")
    aircraft_id: Mapped[int] = fk("aircraft")
    callsign: Mapped[str] = mapped_column(Text)
    formation_pos: Mapped[int] = mapped_column(Integer, default=1)
    hsm_at_launch: Mapped[float | None] = mapped_column(Float)   # hours since maintenance when it flew (D38 exposure)


class SortieCrew(Common, Base):
    __tablename__ = "sortie_crew"
    sortie_id: Mapped[int] = fk("sortie")
    aircrew_id: Mapped[int] = fk("aircrew")
    aircraft_id: Mapped[int] = fk("aircraft")
    position: Mapped[str] = mapped_column(E("CAPTAIN", "CO_PILOT", "WSO", "NAVIGATOR", "FLIGHT_ENGINEER",
                                            "LOADMASTER", "FLIGHT_GUNNER", "RPA_PILOT", "PAYLOAD_OPERATOR",
                                            "INSTRUCTOR", "STUDENT"))
    hours_logged: Mapped[float] = mapped_column(Float, default=0)
    night_hours: Mapped[float] = mapped_column(Float, default=0)


# ---------------------------------------------------------------- E. logistics
class FuelStorage(Common, Base):
    __tablename__ = "fuel_storage"
    base_id: Mapped[int] = fk("base")
    grade: Mapped[str] = mapped_column(E("ATF", "AVGAS", "DIESEL_HSD", "MOGAS"))
    kind: Mapped[str] = mapped_column(E("BULK_UNDERGROUND", "ABOVE_GROUND", "BLADDER"))
    capacity_l: Mapped[float] = mapped_column(Float)
    current_l: Mapped[float] = mapped_column(Float)
    reserve_l: Mapped[float] = mapped_column(Float)
    reorder_l: Mapped[float] = mapped_column(Float)
    tank_count: Mapped[int] = mapped_column(Integer, default=4)
    replenish_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FuelTransaction(Common, Base):
    __tablename__ = "fuel_transaction"
    fuel_storage_id: Mapped[int] = fk("fuel_storage")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(E("RECEIPT", "ISSUE_AIRCRAFT", "ISSUE_VEHICLE", "DEFUEL", "TRANSFER_IN",
                                        "TRANSFER_OUT", "ADJUSTMENT"))
    quantity_l: Mapped[float] = mapped_column(Float)
    balance_after_l: Mapped[float] = mapped_column(Float)
    aircraft_id: Mapped[int | None] = fk("aircraft", nullable=True)
    sortie_id: Mapped[int | None] = fk("sortie", nullable=True)
    actor: Mapped[str] = mapped_column(Text, default="SIMULATOR")


class GroundAsset(Common, Base):
    __tablename__ = "ground_asset"
    base_id: Mapped[int] = fk("base")
    asset_class: Mapped[str] = mapped_column(E("VEHICLE", "GSE"))
    asset_type: Mapped[str] = mapped_column(Text)
    reg_or_serial: Mapped[str] = mapped_column(String(24), unique=True)
    status: Mapped[str] = mapped_column(E("SERVICEABLE", "UNSERVICEABLE", "UNDER_REPAIR"))
    capacity_l: Mapped[float | None] = mapped_column(Float)
    last_service_date: Mapped[date | None] = mapped_column(Date)


class Warehouse(Common, Base):
    __tablename__ = "warehouse"
    base_id: Mapped[int] = fk("base")
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(E("GENERAL", "AVIATION_SPARES", "POL_PACKED", "ARMAMENT_STORE", "MEDICAL",
                                        "RATIONS"))
    capacity_m3: Mapped[float] = mapped_column(Float)
    utilisation_pct: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(E("OPERATIONAL", "DEGRADED", "CLOSED"), default="OPERATIONAL")


STOCK_CATEGORIES = ("ENGINE_SPARES", "AIRFRAME_SPARES", "AVIONICS_SPARES", "TYRES_BRAKES", "CONSUMABLES",
                    "POL_PACKED", "GSE_SPARES", "MEDICAL", "RATIONS", "ARMAMENT_AAM_BVR", "ARMAMENT_AAM_WVR",
                    "ARMAMENT_PGM", "ARMAMENT_BOMB_UNGUIDED", "ARMAMENT_ROCKET", "ARMAMENT_GUN_AMMO",
                    "ARMAMENT_CHAFF_FLARE")


class StockItem(Common, Base):
    __tablename__ = "stock_item"
    part_no: Mapped[str] = mapped_column(String(24), unique=True)
    nomenclature: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(E(*STOCK_CATEGORIES))
    unit: Mapped[str] = mapped_column(E("EA", "L", "KG", "ROUNDS"))
    aircraft_type_id: Mapped[int | None] = fk("aircraft_type", nullable=True)


class StockLevel(Common, Base):
    __tablename__ = "stock_level"
    warehouse_id: Mapped[int] = fk("warehouse")
    stock_item_id: Mapped[int] = fk("stock_item")
    qty_on_hand: Mapped[float] = mapped_column(Float)
    qty_reserved: Mapped[float] = mapped_column(Float, default=0)
    reorder_level: Mapped[float] = mapped_column(Float)
    max_level: Mapped[float] = mapped_column(Float)
    last_receipt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- F. defence & comms
class AdSystemType(Common, Base):
    __tablename__ = "ad_system_type"
    name: Mapped[str] = mapped_column(Text, unique=True)
    category: Mapped[str] = mapped_column(E("LR_SAM", "MR_SAM", "SR_SAM", "VSHORADS", "AD_GUN", "C_UAS"))
    max_range_km: Mapped[float] = mapped_column(Float)
    max_alt_m: Mapped[float | None] = mapped_column(Float)


class AirDefenceBattery(Common, Base):
    __tablename__ = "air_defence_battery"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    ad_system_type_id: Mapped[int] = fk("ad_system_type")
    protected_base_id: Mapped[int | None] = fk("base", nullable=True)
    command_id: Mapped[int | None] = fk("command", nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    status: Mapped[str] = mapped_column(STATUS_SITE, default="OPERATIONAL")
    readiness_min: Mapped[int] = mapped_column(Integer, default=10)
    launchers_total: Mapped[int] = mapped_column(Integer)
    launchers_ready: Mapped[int] = mapped_column(Integer)
    repair_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RadarType(Common, Base):
    __tablename__ = "radar_type"
    name: Mapped[str] = mapped_column(Text, unique=True)
    category: Mapped[str] = mapped_column(E("LONG_RANGE", "MEDIUM_POWER", "LOW_LEVEL_TRANSPORTABLE",
                                            "LOW_LEVEL_LIGHTWEIGHT", "AEROSTAT", "ATC_SURVEILLANCE"))
    max_range_km: Mapped[float] = mapped_column(Float)


class RadarSite(Common, Base):
    __tablename__ = "radar_site"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    radar_type_id: Mapped[int] = fk("radar_type")
    base_id: Mapped[int | None] = fk("base", nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    antenna_height_m: Mapped[float] = mapped_column(Float, default=10)
    status: Mapped[str] = mapped_column(STATUS_SITE, default="OPERATIONAL")
    repair_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommsNode(Common, Base):
    __tablename__ = "comms_node"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    node_type: Mapped[str] = mapped_column(E("DATALINK_GS", "SATCOM_GS", "HF_STATION", "VUHF_RELAY", "C2_NODE",
                                             "NETWORK_HUB"))
    base_id: Mapped[int | None] = fk("base", nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    status: Mapped[str] = mapped_column(E("UP", "DEGRADED", "DOWN"), default="UP")
    repair_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CommsLink(Common, Base):
    __tablename__ = "comms_link"
    node_a_id: Mapped[int] = fk("comms_node")
    node_b_id: Mapped[int] = fk("comms_node")
    medium: Mapped[str] = mapped_column(E("FIBRE", "MICROWAVE", "SATCOM", "HF", "VUHF"))
    status: Mapped[str] = mapped_column(E("UP", "DEGRADED", "DOWN"), default="UP")


# ---------------------------------------------------------------- G. governance
ROLES = ("ADMIN", "COMMAND_HQ", "BASE_COMMANDER", "VIEWER")


class AppUser(Common, Base):
    __tablename__ = "app_user"
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(E(*ROLES))
    base_id: Mapped[int | None] = fk("base", nullable=True)
    command_id: Mapped[int | None] = fk("command", nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    request_id: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(E("USER", "SIMULATOR"))
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_role: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(E("CREATE", "UPDATE", "DELETE", "RETIRE", "LOGIN", "LOGIN_FAILED",
                                          "LOGOUT", "ALERT_ACK", "SIM_CONTROL", "USER_ADMIN", "EXPORT",
                                          "SIM_TRANSITION", "APPROVE", "PLAN_GENERATE", "PLAN_APPROVE",
                                          "PLAN_REJECT", "PLAN_COMMIT", "PLAN_OVERRIDE", "INJECT"))
    entity_type: Mapped[str | None] = mapped_column(Text, index=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    base_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(Text)


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(E("LOW_FUEL", "FUEL_BELOW_RESERVE", "LOW_SERVICEABILITY", "QRA_SHORTFALL",
                                        "CREW_FATIGUE", "CREW_SHORTFALL", "MEDICAL_EXPIRY", "CURRENCY_LAPSE",
                                        "MAINTENANCE_OVERDUE", "STOCK_BELOW_REORDER", "RADAR_DOWN", "AD_DEGRADED",
                                        "COMMS_DOWN", "WX_BELOW_MINIMA", "FEED_STALE", "UNKNOWN_TRACK",
                                        "MISSION_UNCOVERED", "PLAN_AT_RISK", "RETASK_PROPOSED"))
    severity: Mapped[str] = mapped_column(E("INFO", "CAUTION", "WARNING", "CRITICAL"))
    status: Mapped[str] = mapped_column(E("OPEN", "ACKNOWLEDGED", "CLEARED"), default="OPEN", index=True)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    base_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    command_id: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ack_by: Mapped[int | None] = mapped_column(BigInteger)
    ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedup_key: Mapped[str] = mapped_column(Text)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class KpiSnapshot(Base):
    __tablename__ = "kpi_snapshot"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scope: Mapped[str] = mapped_column(E("THEATRE", "COMMAND", "BASE"))
    scope_id: Mapped[int | None] = mapped_column(BigInteger)
    metric: Mapped[str] = mapped_column(Text)
    value: Mapped[float] = mapped_column(Float)


class SimState(Base):
    __tablename__ = "sim_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    seed: Mapped[int] = mapped_column(Integer)
    sim_epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sim_now: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tick_no: Mapped[int] = mapped_column(BigInteger, default=0)
    speed: Mapped[float] = mapped_column(Float, default=10)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    last_programme_date: Mapped[date | None] = mapped_column(Date)


# ---------------------------------------------------------------- I. Phase 2 decision support (PHASE2_IMPLEMENTATION_PLAN §6)
class LoadoutConfig(Common, Base):
    """Generic weapon-load configuration (ARCHITECTURE D30): category counts only, no real store names."""
    __tablename__ = "loadout_config"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(Text)
    role_family: Mapped[str] = mapped_column(Text)
    items: Mapped[dict] = mapped_column(JSONB)                      # {"ARMAMENT_AAM_BVR": 4, ...} per aircraft
    fuel_penalty_pct: Mapped[float] = mapped_column(Float, default=0)
    radius_factor: Mapped[float] = mapped_column(Float, default=1.0)
    description: Mapped[str | None] = mapped_column(Text)


class TypeLoadout(Common, Base):
    __tablename__ = "type_loadout"
    __table_args__ = (UniqueConstraint("aircraft_type_id", "loadout_id"),)
    aircraft_type_id: Mapped[int] = fk("aircraft_type")
    loadout_id: Mapped[int] = fk("loadout_config")


class AirspaceZone(Common, Base):
    __tablename__ = "airspace_zone"
    code: Mapped[str] = mapped_column(String(24), unique=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(E("TRAINING_AREA", "RESTRICTED", "DANGER", "CORRIDOR", "TEMP_RESERVATION", "CIVIL_TERMINAL"))
    geom = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)
    lower_m: Mapped[float] = mapped_column(Float, default=0)
    upper_m: Mapped[float] = mapped_column(Float, default=15000)
    capacity_packages: Mapped[int] = mapped_column(Integer, default=2)
    base_id: Mapped[int | None] = fk("base", nullable=True)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scenario_id: Mapped[int | None] = mapped_column(BigInteger)


class ThreatZone(Common, Base):
    """Generic risk areas (ARCHITECTURE D31): border bands by default, everything else is an exercise inject."""
    __tablename__ = "threat_zone"
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(E("BORDER_BAND", "EXERCISE_SAM", "EXERCISE_CAP", "EXERCISE_EW", "UNKNOWN_ACTIVITY"))
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    risk_level: Mapped[float] = mapped_column(Float)                 # 0..1
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scenario_id: Mapped[int | None] = mapped_column(BigInteger)


class WxBaseForecast(Base):
    __tablename__ = "wx_base_forecast"
    __table_args__ = (UniqueConstraint("base_id", "valid_ts", "source"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    base_id: Mapped[int] = fk("base")
    valid_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ceiling_ft: Mapped[float | None] = mapped_column(Float)          # None = no ceiling
    vis_m: Mapped[float] = mapped_column(Float)
    wind_kt: Mapped[float] = mapped_column(Float, default=0)
    gust_kt: Mapped[float | None] = mapped_column(Float)
    wind_dir: Mapped[float | None] = mapped_column(Float)
    flight_cat: Mapped[str] = mapped_column(E("VFR", "MVFR", "IFR", "LIFR"))
    source: Mapped[str] = mapped_column(E("SYNTHETIC", "OPEN_METEO", "EXERCISE"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


PLAN_STATUS = ("DRAFT", "PROPOSED", "APPROVED", "COMMITTED", "SUPERSEDED", "REJECTED")


class Plan(Base):
    __tablename__ = "plan"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_plan_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(E("PLAN", "RETASK", "WHATIF"), default="PLAN")
    scope: Mapped[str] = mapped_column(E("THEATRE", "COMMAND"), default="THEATRE")
    command_id: Mapped[int | None] = mapped_column(BigInteger)
    horizon_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(E(*PLAN_STATUS), default="PROPOSED", index=True)
    preset: Mapped[str] = mapped_column(Text, default="BALANCED")
    weights: Mapped[dict | None] = mapped_column(JSONB)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    solver_status: Mapped[str | None] = mapped_column(Text)
    solve_ms: Mapped[int | None] = mapped_column(Integer)
    kpis: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger_disruption_id: Mapped[int | None] = mapped_column(BigInteger)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class PlanItem(Base):
    __tablename__ = "plan_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = fk("plan")
    mission_id: Mapped[int] = fk("mission")
    base_id: Mapped[int] = fk("base")
    recovery_base_id: Mapped[int | None] = mapped_column(BigInteger)
    aircraft_type_id: Mapped[int] = fk("aircraft_type", index=False)
    loadout_code: Mapped[str | None] = mapped_column(String(24))
    launch_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    on_station_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_aircraft: Mapped[int] = mapped_column(Integer)
    aircraft_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    aircrew_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    crew_positions: Mapped[list | None] = mapped_column(JSONB)       # [[aircrew_id, aircraft_id, position], ...]
    route_geom = mapped_column(Geometry("LINESTRING", srid=4326))
    risk: Mapped[float] = mapped_column(Float, default=0)
    fuel_l: Mapped[float] = mapped_column(Float, default=0)
    score: Mapped[dict | None] = mapped_column(JSONB)
    explanation: Mapped[dict | None] = mapped_column(JSONB)
    alternatives: Mapped[list | None] = mapped_column(JSONB)
    change: Mapped[str | None] = mapped_column(Text)                 # vs parent plan: KEPT/SWAP/MOVED/NEW/DIVERT
    status: Mapped[str] = mapped_column(E("PROPOSED", "APPROVED", "REJECTED", "COMMITTED", "SUPERSEDED"),
                                        default="PROPOSED")
    sortie_id: Mapped[int | None] = mapped_column(BigInteger)
    source_item_id: Mapped[int | None] = mapped_column(BigInteger)   # the parent-plan item this one replaces
    support: Mapped[dict | None] = mapped_column(JSONB)              # support leg (tanker, D36) with its tails, crew, sortie


class PlanUnmet(Base):
    __tablename__ = "plan_unmet"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plan_id: Mapped[int] = fk("plan")
    mission_id: Mapped[int] = fk("mission")
    reasons: Mapped[list] = mapped_column(JSONB)
    fixes: Mapped[list] = mapped_column(JSONB)
    dropped_item_id: Mapped[int | None] = mapped_column(BigInteger)  # re-task: the parent item that was dropped


class Disruption(Base):
    __tablename__ = "disruption"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(E("AIRCRAFT_US", "CREW_UNAVAILABLE", "RUNWAY_CLOSED", "WX_BELOW_MINIMA",
                                        "THREAT_ACTIVATED", "AIRSPACE_RESERVED", "FUEL_SHORT", "STOCK_SHORT",
                                        "MISSION_NEW", "MISSION_CHANGED", "RECOVERY_UNSAFE", "INJECT"))
    base_id: Mapped[int | None] = mapped_column(BigInteger)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(E("OPEN", "ASSESSED", "RESOLVED", "IGNORED"), default="OPEN", index=True)
    dedup_key: Mapped[str] = mapped_column(Text, index=True)
    impacted_item_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger))
    proposal_plan_id: Mapped[int | None] = mapped_column(BigInteger)
    proposal_ms: Mapped[int | None] = mapped_column(Integer)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # wall clock
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class MaintenanceEvent(Base):
    """Maintenance log (D38): defects found before, during or after a sortie, and scheduled inspections. The snag-risk
    model (decide/predict.py) learns from this log joined to the sorties each tail flew."""
    __tablename__ = "maintenance_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    aircraft_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("aircraft.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(E("PREFLIGHT", "AIRBORNE", "POSTFLIGHT", "SCHEDULED"))
    sortie_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    hours_since_maint: Mapped[float] = mapped_column(Float)
    airframe_hours: Mapped[float] = mapped_column(Float)
    planned_h: Mapped[float | None] = mapped_column(Float)      # the sortie's planned length (defects only)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class MlModel(Base):
    """A trained model and its card (D38). Only `snag_risk` today; the newest row per name is the one in use."""
    __tablename__ = "ml_model"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())   # wall clock
    data_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))                              # sim time
    features: Mapped[list] = mapped_column(JSONB)
    coef: Mapped[list] = mapped_column(JSONB)
    scale: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ManualSession(Base):
    """Manual planning baseline (D43): one timed attempt to plan a snapshot by hand, and the optimiser on the same one."""
    __tablename__ = "manual_session"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())   # wall clock
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sim_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    missions: Mapped[int] = mapped_column(Integer, default=0)
    checks: Mapped[int] = mapped_column(Integer, default=0)
    picks: Mapped[list | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)        # manual coverage / violations, optimiser on the same snapshot
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Scenario(Base):
    __tablename__ = "scenario"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    speed: Mapped[float] = mapped_column(Float, default=60)
    injects: Mapped[list] = mapped_column(JSONB)                     # [{offset_min, kind, params, label}]
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class ExerciseRun(Base):
    __tablename__ = "exercise_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    scenario_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(E("RUNNING", "ENDED"), default="RUNNING", index=True)
    started_real: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_sim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_sim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    injects: Mapped[list] = mapped_column(JSONB, default=list)       # scenario injects + live ones, with applied_at
    kpi_timeline: Mapped[list] = mapped_column(JSONB, default=list)  # [{sim_ts, metric: value...}]
    started_by: Mapped[int | None] = mapped_column(BigInteger)


# ---------------------------------------------------------------- H. static GIS (pipeline-owned)
class GisAdminArea(Base):
    __tablename__ = "gis_admin_area"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    level: Mapped[str] = mapped_column(E("ADM0", "ADM1", "ADM2"), index=True)
    country_iso3: Mapped[str] = mapped_column(String(3), index=True)
    name: Mapped[str | None] = mapped_column(Text)
    parent_name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    geom_lo = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    geom_mid = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    label_pt = mapped_column(Geometry("POINT", srid=4326))


class GisPlace(Base):
    __tablename__ = "gis_place"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    population: Mapped[int] = mapped_column(Integer, index=True)
    admin1: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    geom = mapped_column(Geometry("POINT", srid=4326))


class GisLine(Base):
    __tablename__ = "gis_line"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(E("MOTORWAY", "TRUNK", "PRIMARY", "RAIL"), index=True)
    name: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[str | None] = mapped_column(Text)
    geom = mapped_column(Geometry("LINESTRING", srid=4326))
    geom_simplified = mapped_column(Geometry("LINESTRING", srid=4326))


class GisPoint(Base):
    __tablename__ = "gis_point"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, index=True)
    osm_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str | None] = mapped_column(Text)
    height_m: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(SmallInteger)  # RAIL_STATION importance: 0 major … 2 minor
    geom = mapped_column(Geometry("POINT", srid=4326))


class GisDefactoAdmin0(Base):
    """Natural Earth default (de facto control) admin-0. PLANNING ONLY: never rendered, never served as a boundary
    (AGENTS §9). The planner uses it so no route or mission is placed beyond the LoC / LAC (ARCHITECTURE D33)."""
    __tablename__ = "gis_defacto_admin0"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    iso3: Mapped[str] = mapped_column(String(3), index=True)
    name: Mapped[str] = mapped_column(Text)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326))


class CivilAirport(Base):
    __tablename__ = "civil_airport"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ident: Mapped[str] = mapped_column(Text, unique=True)
    icao: Mapped[str | None] = mapped_column(Text)
    iata: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, index=True)
    country_iso2: Mapped[str] = mapped_column(String(2))
    elevation_m: Mapped[float | None] = mapped_column(Float)
    geom = mapped_column(Geometry("POINT", srid=4326))
