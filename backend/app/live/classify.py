# Portions derived from God's Eye View (src/data/aircraftClass.js, src/data/aircraftEmergency.js),
# Copyright (c) 2026 Bilawal Sidhu, MIT License. Type sets originally adapted from skylight
# (https://github.com/cpaczek/skylight, MIT). See THIRD_PARTY_NOTICES.md.
"""Aircraft glyph class + display category (FR-LIVE-03)."""


def _s(text: str) -> frozenset[str]:
    return frozenset(text.split())


HELI = _s("EC20 EC25 EC30 EC35 EC45 EC55 AS50 AS55 AS65 AS32 A109 A119 A139 A169 A189 B06 B06T B407 B412 B427 B429 "
          "B430 B505 S76 S92 S61 S64 H60 H500 MD52 MD60 R22 R44 R66 EXEC EXPL GAZL LYNX NH90 PUMA SCAV UH1 B105 B212 "
          "B214 B222 AC H47 H64 "
          "MI8 MI17 MI24 MI26 ALH LCH ALO3 LAMA KA28 KA31")                          # + Indian service types
QUAD = _s("B741 B742 B743 B744 B748 B74S B74R B74D A388 A342 A343 A345 A346 A124 C5M A225 IL96 B52 A140")
WIDE = _s("A306 A30B A310 A332 A333 A338 A339 A359 A35K B762 B763 B764 B772 B77L B773 B77W B778 B779 B788 B789 B78X "
          "MD11 IL86 DC10 L101 A337 B767 B777 B787 C17 K35R IL76 IL78 A50")
TPROP = _s("DH8A DH8B DH8C DH8D AT43 AT44 AT45 AT46 AT72 AT73 AT75 AT76 SF34 SB20 SW3 SW4 E110 E120 C208 C212 C408 "
           "PC12 B190 BE20 B350 B300 JS31 JS32 JS41 D228 D328 F50 F27 ATP TBM7 TBM8 TBM9 TBM0 PC6 C441 C425 DHC6 DHC7 "
           "C130 AN12 AN26 AN32 SH36 CVLT SAAB A400 C30J C295 PC7 PC9 HT40")
LIGHT = _s("C150 C152 C162 C172 C72R C175 C177 C180 C182 C185 C188 C206 C207 C210 C310 C337 SR20 SR22 S22T PA18 PA24 "
           "PA28 P28A P28B P28R PA32 P32R PA34 PA38 PA44 PA46 DA20 DA40 DA42 DA62 BE33 BE35 BE36 BE58 BE76 BE19 BE23 "
           "BE24 M20P M20T AA1 AA5 GLAS COL4 RV4 RV6 RV7 RV8 RV9 RV10 RV14 GA8 G115 BL8 CH7 VIRU")
BIZJET = _s("C500 C501 C510 C525 C25A C25B C25C C25M C550 C551 C560 C56X C650 C680 C68A C700 C750 CL30 CL35 CL60 GLF2 "
            "GLF3 GLF4 GLF5 GLF6 GA5C GA6C G150 G280 GL5T GL7T GLEX LJ23 LJ24 LJ25 LJ31 LJ35 LJ40 LJ45 LJ55 LJ60 LJ70 "
            "LJ75 FA10 FA20 FA50 FA7X FA8X F900 F2TH H25A H25B H25C HDJT E50P E55P E545 E550 PC24 PRM1 BE40 ASTR WW24 "
            "SF50 E135 E145")
UAV = _s("Q1 Q4 Q9 MQ1 MQ4 MQ9 RQ4 TB2 SHDW HERN SRCH")
SMALL_UAS = _s("DRON UAS")
FASTJET = _s("F16 F15 F18 FA18 F14 F22 F35 F4 F5 A10 AV8B TYPH EUFI RFAL RAFL GRIP JAS39 TOR MIR2 M2000 SU27 SU30 SU33 "
             "SU34 SU35 SU57 MG29 MIG29 MG31 J20 T38 HAWK L39 M346 T7A JAGR JAGU LCA TEJA MG21 MG27 HJT6 JF17 J10 J11")
GLIDER = _s("DISC DUOD VENT NIMB NIM3 NIM4 JANS ARCE DG40 DG80 DG1T DG30 DG50 LS3 LS4 LS6 LS7 LS8 STD3 G103 G102 G104 "
            "PW5 PW6 L13 L23 L33 PIK PEGA KEST TWIN AS33 ASW ASG ASK VENS GLID MOSQ DIMO")
OPENSKY_CATEGORY = {2: "light", 3: "airliner", 4: "airliner", 5: "airliner", 6: "widebody", 7: "fastjet",
                    8: "helicopter", 9: "glider", 14: "uav"}
EMITTER_CATEGORY = {"A1": "light", "A2": "light", "A3": "airliner", "A4": "airliner", "A5": "widebody",
                    "A6": "fastjet", "A7": "helicopter", "B1": "glider", "B6": "uav"}
# ICAO airline designators flying freighters (callsign prefix). Extend freely.
CARGO_OPERATORS = _s("BDA FDX UPS GTI CLX CKS ABW SQC CAO CKK DHK BCS DHX TAY MPH ICV AHK NCA QAC BOX GEC "
                     "CLU KYE PAC SOO AJT LCO MAS UAE5 TGX CSS QPE MXU")
EMERGENCY = {"7500": "HIJACK", "7600": "RADIO FAILURE", "7700": "EMERGENCY"}


def aircraft_class(type_code: str | None, category) -> str:
    code = (type_code or "").strip().upper()
    if code:
        for name, group in (("fastjet", FASTJET), ("uav", UAV), ("drone", SMALL_UAS), ("helicopter", HELI),
                            ("quadjet", QUAD), ("widebody", WIDE), ("turboprop", TPROP), ("glider", GLIDER),
                            ("bizjet", BIZJET), ("light", LIGHT)):
            if code in group:
                return name
        return "airliner"
    if isinstance(category, int) and category in OPENSKY_CATEGORY:
        return OPENSKY_CATEGORY[category]
    return EMITTER_CATEGORY.get(str(category or "").strip().upper(), "airliner")


def display_category(track: dict) -> str:
    """Precedence: MILITARY > UAV > DRONE > HELICOPTER > CARGO > CIVIL (simulated tracks never come through here)."""
    cls = track["cls"]
    if track["is_military"]:
        return "MILITARY"
    if cls == "uav":
        return "DRONE" if not track.get("icao_type") and (track.get("alt_m") or 0) < 500 else "UAV"
    if cls == "drone":
        return "DRONE"
    if cls == "helicopter":
        return "HELICOPTER"
    if (track.get("callsign") or "")[:3].upper() in CARGO_OPERATORS:
        return "CARGO"
    return "CIVIL"


def emergency(squawk: str | None, flag: str | None = None) -> str | None:
    if flag and flag not in ("none", ""):
        return flag.upper()
    return EMERGENCY.get(str(squawk or ""))


if __name__ == "__main__":  # smallest check that fails if the precedence logic breaks
    base = {"is_military": False, "callsign": "", "icao_type": "B77W", "alt_m": 10000}
    assert display_category({**base, "cls": aircraft_class("B77W", None)}) == "CIVIL"
    assert display_category({**base, "cls": aircraft_class("B77L", None), "callsign": "FDX5021"}) == "CARGO"
    assert display_category({**base, "cls": aircraft_class("MI8", None)}) == "HELICOPTER"
    assert display_category({**base, "cls": aircraft_class("HERN", None)}) == "UAV"
    assert display_category({**base, "cls": aircraft_class(None, "B6"), "icao_type": None, "alt_m": 120}) == "DRONE"
    assert display_category({**base, "cls": aircraft_class("C295", None), "is_military": True}) == "MILITARY"
    assert aircraft_class(None, 8) == "helicopter" and emergency("7700") == "EMERGENCY"
    print("classify self-check ok")
