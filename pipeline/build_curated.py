"""Build data/curated/*.csv from hand-curated public seed lists + OurAirports coordinates.

Every row is PUBLIC information with a source URL and is flagged verify=1 until a human checks it
(DATA_MODEL §8.1, Appendix A). Run: .venv/bin/python pipeline/build_curated.py
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data" / "raw", ROOT / "data" / "curated"
WIKI_STATIONS = "https://en.wikipedia.org/wiki/List_of_Indian_Air_Force_stations"
WIKI_AIRCRAFT = "https://en.wikipedia.org/wiki/List_of_active_Indian_military_aircraft"

# ident (OurAirports) | display name | command | wing | base_type | role_tags | size S/M/L
IAF_BASES = """
VIAX|Air Force Station Adampur|WAC|8 Wing|AIR_FORCE_STATION|FIGHTER|L
VIAM|Air Force Station Ambala|WAC|7 Wing|AIR_FORCE_STATION|FIGHTER|L
VIAR|Air Force Station Amritsar|WAC|1 FBSU|FBSU|FIGHTER|S
VIAW|Air Force Station Awantipur|WAC|8 FBSU|FBSU|FIGHTER|M
VIBT|Air Force Station Bathinda|WAC|34 Wing|AIR_FORCE_STATION|FIGHTER,AEW,UAV|M
VICG|Air Force Station Chandigarh|WAC|12 Wing|AIR_FORCE_STATION|TRANSPORT,HELO|L
VIHX|Air Force Station Halwara|WAC|9 Wing|AIR_FORCE_STATION|FIGHTER|L
VIDX|Air Force Station Hindon|WAC|28 Wing|AIR_FORCE_STATION|TRANSPORT,HELO|L
VIJU|Air Force Station Jammu|WAC|23 Wing|JOINT_USE|HELO|M
VILH|Air Force Station Leh|WAC|21 Wing|JOINT_USE|HELO,TRANSPORT,FIGHTER|M
VI57|Air Force Station Thoise|WAC||FBSU|TRANSPORT,HELO|S
VIDP|Air Force Station Palam|WAC|3 Wing|AIR_FORCE_STATION|TRANSPORT|L
VIPK|Air Force Station Pathankot|WAC|18 Wing|AIR_FORCE_STATION|HELO,FIGHTER|M
VISP|Air Force Station Sarsawa|WAC|30 Wing|AIR_FORCE_STATION|HELO|M
VISA|Air Force Station Sirsa|WAC|45 Wing|AIR_FORCE_STATION|FIGHTER|M
VISR|Air Force Station Srinagar|WAC|1 Wing|AIR_FORCE_STATION|FIGHTER,HELO|M
VIUX|Air Force Station Udhampur|WAC|39 Wing|HELIBASE|HELO|S
VABJ|Air Force Station Bhuj|SWAC|27 Wing|AIR_FORCE_STATION|FIGHTER|M
VADS|Air Force Station Deesa|SWAC|52 Wing|AIR_FORCE_STATION|FIGHTER|M
VIJR|Air Force Station Jaisalmer|SWAC|41 Wing|AIR_FORCE_STATION|FIGHTER,UAV|M
VAJM|Air Force Station Jamnagar|SWAC|33 Wing|AIR_FORCE_STATION|FIGHTER|L
VIJO|Air Force Station Jodhpur|SWAC|32 Wing|AIR_FORCE_STATION|FIGHTER,HELO|L
VAPO|Air Force Station Lohegaon (Pune)|SWAC|2 Wing|AIR_FORCE_STATION|FIGHTER|L
VIBK|Air Force Station Nal (Bikaner)|SWAC|46 Wing|AIR_FORCE_STATION|FIGHTER|M
VA1K|Air Force Station Naliya|SWAC|49 Wing|AIR_FORCE_STATION|FIGHTER|M
VIPX|Air Force Station Phalodi|SWAC|35 Wing|AIR_FORCE_STATION|HELO|M
VI43|Air Force Station Suratgarh|SWAC||AIR_FORCE_STATION|HELO|S
VIUT|Air Force Station Uttarlai|SWAC|5 FBSU|FBSU|FIGHTER|M
VABO|Air Force Station Vadodara|SWAC|36 Wing|AIR_FORCE_STATION|TRANSPORT|M
VIAG|Air Force Station Agra|CAC|4 Wing|AIR_FORCE_STATION|TRANSPORT,AEW,TANKER|L
VIBL|Air Force Station Bakshi Ka Talab|CAC||AIR_FORCE_STATION|TRANSPORT|S
VIAL|Air Force Station Bamrauli (Prayagraj)|CAC|29 Wing|AIR_FORCE_STATION|TRANSPORT,HELO|M
VIBY|Air Force Station Bareilly|CAC|15 Wing|AIR_FORCE_STATION|FIGHTER,HELO|L
IN-0346|Air Force Station Bihta|CAC||AIR_FORCE_STATION|TRANSPORT|S
VEDH|Air Force Station Darbhanga|CAC||JOINT_USE|TRANSPORT|S
VEGK|Air Force Station Gorakhpur|CAC|17 Wing|AIR_FORCE_STATION|FIGHTER,HELO|L
VIGR|Air Force Station Gwalior|CAC|40 Wing|AIR_FORCE_STATION|FIGHTER|L
VEBD|Air Force Station Bagdogra|EAC|20 Wing|AIR_FORCE_STATION|HELO,FIGHTER|M
VEPI|Air Force Station Barrackpore|EAC|6 Wing|AIR_FORCE_STATION|HELO|M
VECA|Air Force Station Chabua|EAC|14 Wing|AIR_FORCE_STATION|FIGHTER|M
VEHX|Air Force Station Hasimara|EAC|16 Wing|AIR_FORCE_STATION|FIGHTER|M
VEJT|Air Force Station Jorhat|EAC|10 Wing|AIR_FORCE_STATION|TRANSPORT,HELO|L
VEDX|Air Force Station Kalaikunda|EAC|5 Wing|AIR_FORCE_STATION|FIGHTER,TRAINING|L
VEKU|Air Force Station Kumbhigram|EAC|22 Wing|JOINT_USE|HELO|S
VEMN|Air Force Station Mohanbari|EAC|42 Wing|JOINT_USE|HELO|M
VEPH|Air Force Station Panagarh|EAC||AIR_FORCE_STATION|TRANSPORT|L
VEPU|Air Force Station Purnea|EAC|14 FBSU|FBSU|FIGHTER|S
VEBI|Air Force Station Shillong (Barapani)|EAC||JOINT_USE|TRANSPORT|S
VETZ|Air Force Station Tezpur|EAC|11 Wing|AIR_FORCE_STATION|FIGHTER|L
IN-0002|Air Force Station Tawang|EAC||HELIBASE|HELO|S
IN-0019|Air Force Station Dinjan|EAC||HELIBASE|HELO|S
VOCX|Air Force Station Car Nicobar|SAC|37 Wing|AIR_FORCE_STATION|FIGHTER,TRANSPORT|M
VOSX|Air Force Station Sulur|SAC|43 Wing|AIR_FORCE_STATION|FIGHTER,TRANSPORT,HELO|L
VOTX|Air Force Station Tambaram|SAC||TRAINING_ESTABLISHMENT|TRAINING|S
VOTJ|Air Force Station Thanjavur|SAC|47 Wing|AIR_FORCE_STATION|FIGHTER|M
VOTV|Air Force Station Thiruvananthapuram|SAC||JOINT_USE|TRANSPORT|S
VOHY|Air Force Station Begumpet|TC||TRAINING_ESTABLISHMENT|TRAINING|M
VOBR|Air Force Station Bidar|TC||TRAINING_ESTABLISHMENT|TRAINING|L
VODG|Air Force Academy Dundigal|TC||TRAINING_ESTABLISHMENT|TRAINING|L
VOHK|Air Force Station Hakimpet|TC||TRAINING_ESTABLISHMENT|TRAINING,HELO|M
VOYK|Air Force Station Yelahanka|TC||TRAINING_ESTABLISHMENT|TRAINING,TRANSPORT|M
VANP|Air Force Station Nagpur (Sonegaon)|MC|44 Wing|AIR_FORCE_STATION|MAINT|M
VAOZ|11 Base Repair Depot Ojhar|MC||BASE_REPAIR_DEPOT|MAINT|M
VICX|Air Force Station Kanpur (Chakeri)|MC||BASE_REPAIR_DEPOT|MAINT|M
"""

ALGS = """
IN-0003|Daulat Beg Oldi ALG|WAC
IN-0302|Nyoma ALG|WAC
VI66|Fukche ALG|WAC
VI65|Kargil ALG|WAC
VE67|Mechuka ALG|EAC
VE91|Vijaynagar ALG|EAC
IN-0010|Walong ALG|EAC
IN-0307|Tuting ALG|EAC
VEPG|Pasighat ALG|EAC
VEAN|Along ALG|EAC
VEZO|Ziro ALG|EAC
"""

# ident | name | operator | notes
OTHER_INDIAN_MIL = """
VOGO|INS Hansa (Goa)|IN|Indian Navy air station (joint use with Dabolim)
VOAR|INS Rajali (Arakkonam)|IN|Indian Navy air station
VEVZ|INS Dega (Visakhapatnam)|IN|Indian Navy air station (joint use)
VOCC|INS Garuda (Kochi)|IN|Indian Navy air station
VORM|INS Parundu (Ramanathapuram)|IN|Indian Navy air station
VO94|INS Baaz (Campbell Bay)|IN|Indian Navy air station
IN-0053|INS Kohassa (Shibpur)|IN|Indian Navy air station
VOPB|INS Utkrosh (Port Blair)|IN|Indian Navy air station (joint use)
IN-0021|INS Shikra (Mumbai)|IN|Indian Navy helibase
IN-0382|Army Aviation Gandhinagar (Nashik)|IA_AVN|Army Aviation (combat army aviation training school area)
VADN|Coast Guard Air Station Daman|ICG|Indian Coast Guard air station
VAPR|Coast Guard Air Enclave Porbandar|ICG|Indian Coast Guard air enclave (joint use)
"""

# ident | country iso3 | operator | notes
NEIGHBOUR_BASES = """
OPMR|PAK|PAF|PAF Base Masroor (Karachi)
OPSF|PAK|PAF|PAF Base Faisal (Karachi)
OPSR|PAK|PAF|PAF Base Mushaf (Sargodha)
OPMI|PAK|PAF|PAF Base M.M. Alam (Mianwali)
OPMS|PAK|PAF|PAF Base Minhas (Kamra)
OPRN|PAK|PAF|PAF Base Nur Khan (Rawalpindi)
OPRQ|PAK|PAF|PAF Base Rafiqui (Shorkot)
OPRS|PAK|PAF|PAF Base Risalpur
OPJA|PAK|PAF|PAF Base Shahbaz (Jacobabad)
PK-0009|PAK|PAF|PAF Base Murid
PK-0049|PAK|PAF|PAF Base Samungli / Khalid (Quetta)
PK-0070|PAK|PAF|PAF Base Bholari
OPMK|PAK|PAF|Mirpur Khas air base
OP24|PAK|PAF|Mandi Bahauddin air base
ZWSH|CHN|PLAAF|Kashgar (joint use)
ZWTN|CHN|PLAAF|Hotan (joint use)
ZUAL|CHN|PLAAF|Ngari Gunsa (joint use)
CN-0354|CHN|PLAAF|Ali Burang / Pulan (joint use)
ZULS|CHN|PLAAF|Lhasa Gonggar (joint use)
ZURK|CHN|PLAAF|Shigatse Peace (joint use)
CN-0236|CHN|PLAAF|Shigatse Tingri (joint use)
ZUNZ|CHN|PLAAF|Nyingchi Mainling (joint use)
ZUBD|CHN|PLAAF|Qamdo Bangda (joint use)
CN-0033|CHN|PLAAF|Damxung air base
ZUSH|CHN|PLAAF|Shannan Longzi (joint use)
CN-0237|CHN|PLAAF|Tashkurgan (joint use)
CN-0049|CHN|PLAAF|Xiangyun Midu air base
VQPR|BTN|CIVIL_JOINT|Paro International (no air force)
VGHS|BGD|BAF|BAF Base Bangabandhu (Dhaka, joint use)
VGEG|BGD|BAF|BAF Base Zahurul Haque (Chattogram, joint use)
VGJR|BGD|BAF|BAF Base Matiur Rahman (Jessore)
VGSD|BGD|BAF|Saidpur (joint use)
VNKT|NPL|NA_AVN|Tribhuvan International (Nepal Army Air Service)
VCCH|LKA|SLAF|SLAF Hingurakgoda
VCCN|LKA|SLAF|SLAF Katukurunda
VCCT|LKA|SLAF|SLAF China Bay
VCCJ|LKA|SLAF|SLAF Palaly / Jaffna (joint use)
VYML|MMR|MAF|Meiktila air base
VYST|MMR|MAF|Shante air base
VYNP|MMR|MAF|Namsang / Nampong air base
VYMK|MMR|MAF|Myitkyina (joint use)
OAIX|AFG|AAF|Bagram airfield
OASD|AFG|AAF|Shindand air base
"""

# number | name | aircraft type | base ident        (public ORBAT, VERIFY every row)
SQUADRONS = """
1 Sqn|Tigers|Mirage 2000|VIGR
7 Sqn|Battle Axes|Mirage 2000|VIGR
9 Sqn|Wolfpack|Mirage 2000|VIGR
5 Sqn|Tuskers|Jaguar|VIAM
14 Sqn|Bulls|Jaguar|VIAM
16 Sqn|Black Cobras|Jaguar|VEGK
27 Sqn|Flaming Arrows|Jaguar|VEGK
6 Sqn|Dragons|Jaguar|VAJM
224 Sqn|Warlords|Jaguar|VAJM
17 Sqn|Golden Arrows|Rafale|VIAM
101 Sqn|Falcons|Rafale|VEHX
28 Sqn|First Supersonics|MiG-29|VIAX
47 Sqn|Black Archers|MiG-29|VIAX
223 Sqn|Tridents|MiG-29|VIAX
2 Sqn|Winged Arrows|Su-30MKI|VETZ
106 Sqn|Lynxes|Su-30MKI|VETZ
8 Sqn|Eight Pursoots|Su-30MKI|VIBY
24 Sqn|Hunting Hawks|Su-30MKI|VIBY
15 Sqn|Flying Lancers|Su-30MKI|VISA
20 Sqn|Lightnings|Su-30MKI|VAPO
30 Sqn|Rhinos|Su-30MKI|VAPO
31 Sqn|Lions|Su-30MKI|VIJO
102 Sqn|Trisonics|Su-30MKI|VECA
220 Sqn|Desert Tigers|Su-30MKI|VIHX
221 Sqn|Valiants|Su-30MKI|VIHX
222 Sqn|Tigersharks|Su-30MKI|VOTJ
4 Sqn|Oorials|Su-30MKI|VIUT
45 Sqn|Flying Daggers|Tejas Mk1|VOSX
18 Sqn|Flying Bullets|Tejas Mk1|VA1K
81 Sqn|Skylords|C-17A|VIDX
77 Sqn|Veiled Vipers|C-130J-30|VIDX
87 Sqn|Ironsides|C-130J-30|VEPH
44 Sqn|Mighty Jets|Il-76MD|VICG
78 Sqn|Mighty Monsters|Il-78MKI|VIAG
50 Sqn|Heavyweights|A-50EI|VIAG
Netra Flight||Netra EMB-145I|VIBT
11 Sqn|Rhinos|C-295W|VABO
12 Sqn|Yaks|An-32|VIAG
25 Sqn|Himalayan Eagles|An-32|VICG
48 Sqn|Camels|An-32|VICG
33 Sqn|Caribous|An-32|VOSX
43 Sqn|Ibexes|An-32|VEJT
49 Sqn|Paraketes|An-32|VEJT
41 Sqn|Otters|Do-228|VIDP
125 HS|Gladiators|AH-64E|VIPK
137 HS||AH-64E|VEJT
126 HF|Featherweights|CH-47F|VICG
143 HU|Dhanush|Prachand LCH|VIJO
104 HS|Firebirds|Mi-35|VI43
116 HU||Rudra|VIJO
105 HU|Daredevils|Mi-17V-5|VEGK
107 HU||Mi-17V-5|VIJO
109 HU|Knights|Mi-17V-5|VOSX
127 HU||Mi-17V-5|VEMN
128 HU||Mi-17V-5|VEMN
129 HU||Mi-17V-5|VIDX
130 HU|Condors|Mi-17V-5|VILH
152 HU||Mi-17V-5|VISP
153 HU||Mi-17V-5|VIJU
154 HU||Mi-17V-5|VISR
156 HU||Mi-17V-5|VEBD
157 HU||Mi-17V-5|VEPI
111 HU||Dhruv|VIBY
117 HU||Dhruv|VISP
114 HU|Siachen Pioneers|Cheetah/Chetak|VILH
131 HF||Cheetah/Chetak|VIDX
132 HF||Cheetah/Chetak|VIUX
AFA Basic Flying||PC-7 Mk II|VODG
AFA Kiran Flight||Kiran|VODG
FTW Hakimpet||Kiran|VOHK
HTS Hakimpet||Cheetah/Chetak|VOHK
Hawk Training Bidar||Hawk 132|VOBR
Hawk Training Kalaikunda||Hawk 132|VEDX
TTW Yelahanka||Do-228|VOYK
"""

# name|icao|variant|manufacturer|category|role|seats_pilot|seats_other|max_fuel_kg|burn_kg_h|cruise_kt|endurance_h|radius_km|slot|maint_h|turn_min|prefix|sidc|in_service|target
AIRCRAFT_TYPES = """
Su-30MKI|SU30|Su-30MKI|Sukhoi/HAL|FIXED_WING|FIGHTER_MULTIROLE|1|1|9400|3400|480|3.0|1500|M|100|45|SB|MF|1|258
Rafale|RFAL|Rafale EH/DH|Dassault|FIXED_WING|FIGHTER_MULTIROLE|1|0|4700|2500|480|2.5|1850|M|120|40|RB|MF|1|36
Tejas Mk1|LCA|Tejas Mk1|HAL|FIXED_WING|FIGHTER_MULTIROLE|1|0|2450|1500|450|1.7|500|M|100|35|LA|MF|1|38
MiG-29|MG29|MiG-29UPG|Mikoyan|FIXED_WING|AIR_SUPERIORITY|1|0|3500|2700|470|1.6|700|M|100|40|KB|MF|1|59
Mirage 2000|MIR2|Mirage 2000I/TI|Dassault|FIXED_WING|FIGHTER_MULTIROLE|1|0|3200|2200|470|1.8|1480|M|100|40|KF|MF|1|46
Jaguar|JAGR|Jaguar IS/IM/IB|SEPECAT/HAL|FIXED_WING|STRIKE|1|0|3300|2400|430|1.7|850|M|100|40|JS|MF|1|112
Il-78MKI|IL78|Il-78MKI|Ilyushin|FIXED_WING|TANKER|2|4|90000|7000|400|10|0|XL|200|120|RK|MFK|1|6
A-50EI|A50|A-50EI|Beriev|FIXED_WING|AEW_C|2|13|60000|6500|400|9|0|XL|200|120|KW|MFRW|1|3
Netra EMB-145I|E145|Netra Mk1|Embraer/DRDO|FIXED_WING|AEW_C|2|4|5100|1100|400|5|0|L|200|90|KX|MFRW|1|3
C-17A|C17|C-17A Globemaster III|Boeing|FIXED_WING|TRANSPORT_STRATEGIC|2|1|102000|7500|450|10|0|XL|250|120|CB|MFC|1|11
Il-76MD|IL76|Il-76MD|Ilyushin|FIXED_WING|TRANSPORT_STRATEGIC|2|4|85000|7000|420|9|0|XL|200|120|KI|MFC|1|17
C-130J-30|C30J|C-130J-30 Super Hercules|Lockheed Martin|FIXED_WING|TRANSPORT_TACTICAL|2|2|20800|2400|340|10|0|L|250|90|KC|MFC|1|12
C-295W|C295|C-295W|Airbus/TASL|FIXED_WING|TRANSPORT_TACTICAL|2|1|6000|750|260|8|0|L|250|60|KT|MFC|1|16
An-32|AN32|An-32RE|Antonov|FIXED_WING|TRANSPORT_TACTICAL|2|3|5500|1100|260|5|0|L|200|60|K|MFC|1|102
Do-228|D228|Do-228-201|Dornier/HAL|FIXED_WING|TRANSPORT_LIGHT|2|0|1900|250|200|7|0|M|200|40|HM|MFC|1|62
Mi-17V-5|MI8|Mi-17V-5|Mil|ROTARY_WING|UTILITY_HELO|2|1|2600|750|130|3.0|0|M|150|30|ZP|MHU|1|222
Dhruv|ALH|Dhruv Mk I/III|HAL|ROTARY_WING|UTILITY_HELO|2|0|1100|300|135|3.5|0|S|150|25|J|MHU|1|95
Rudra|ALH|Rudra (ALH WSI)|HAL|ROTARY_WING|ATTACK_HELO|2|0|1100|320|135|3.0|0|S|150|25|JR|MHA|1|16
Prachand LCH|LCH|Prachand|HAL|ROTARY_WING|ATTACK_HELO|2|0|1000|300|145|3.0|0|S|150|25|ZG|MHA|1|10
AH-64E|H64|AH-64E Apache Guardian|Boeing|ROTARY_WING|ATTACK_HELO|2|0|1150|500|145|2.5|0|M|150|30|ZD|MHA|1|22
Mi-35|MI24|Mi-25/35P|Mil|ROTARY_WING|ATTACK_HELO|2|1|1500|650|140|2.5|0|M|150|30|Z|MHA|1|15
CH-47F|H47|CH-47F(I) Chinook|Boeing|ROTARY_WING|HEAVY_LIFT_HELO|2|2|3100|1200|150|3.0|0|L|150|40|ZA|MHC|1|15
Cheetah/Chetak|ALO3|Chetak/Cheetah/Cheetal|HAL|ROTARY_WING|LIGHT_HELO|1|1|450|160|100|2.5|0|S|120|20|Z|MHU|1|115
Hawk 132|HAWK|Hawk Mk132|BAE/HAL|FIXED_WING|TRAINER_ADVANCED|2|0|1360|700|400|2.0|0|M|120|30|A|MFT|1|102
Kiran|HJT6|HJT-16 Kiran Mk I/II|HAL|FIXED_WING|TRAINER_INTERMEDIATE|2|0|1000|600|300|1.5|0|S|100|25|U|MFT|1|77
PC-7 Mk II|PC7|PC-7 Mk II|Pilatus|FIXED_WING|TRAINER_BASIC|2|0|380|100|220|3.5|0|S|120|20|P|MFT|1|74
HTT-40|HT40|HTT-40|HAL|FIXED_WING|TRAINER_BASIC|2|0|400|110|240|3.0|0|S|120|20|HT|MFT|1|3
Heron Mk II|HERN|Heron Mk II|IAI|UAV_FIXED_WING|UAV_MALE|1|1|400|20|80|24|1000|M|300|90|HR|MFQ|1|9
Searcher Mk II|SRCH|Searcher Mk II|IAI|UAV_FIXED_WING|UAV_TACTICAL|1|1|100|10|70|15|300|S|200|60|SR|MFQ|1|8
Small UAS (generic)|DRON|Generic multirotor|Various|UAV_ROTARY_SMALL|SMALL_UAS|1|0|2|1|30|0.6|10|S|50|10|UA|MHQ|1|0
MiG-21 Bison|MG21|MiG-21 Bison|Mikoyan/HAL|FIXED_WING|FIGHTER_MULTIROLE|1|0|2200|2000|450|1.2|500|M|100|40|C|MF|0|0
MiG-27|MG27|MiG-27ML|Mikoyan/HAL|FIXED_WING|STRIKE|1|0|4500|2800|450|1.5|540|M|100|40|TS|MF|0|0
HPT-32|HPT3|HPT-32 Deepak|HAL|FIXED_WING|TRAINER_BASIC|2|0|200|60|130|4.0|0|S|100|20|X|MFT|0|0
"""

AD_SYSTEMS = [  # name, category, range km, ceiling m  (approximate public figures, VERIFY)
    ("S-400 Triumf (Sudarshan Chakra)", "LR_SAM", 380, 30000), ("MR-SAM (Barak-8)", "MR_SAM", 70, 16000),
    ("Akash-NG", "MR_SAM", 70, 20000), ("Akash", "SR_SAM", 25, 18000), ("SPYDER-MR", "SR_SAM", 35, 16000),
    ("SPYDER-SR", "SR_SAM", 15, 9000), ("S-125 Pechora (upgraded)", "SR_SAM", 25, 18000),
    ("Igla-S", "VSHORADS", 6, 3500), ("L/70 40 mm AD gun", "AD_GUN", 4, 3000), ("ZU-23-2 twin 23 mm", "AD_GUN", 2.5, 1500),
    ("Counter-drone system (generic)", "C_UAS", 3, 1000),
]
RADARS = [  # name, category, range km (approximate public figures, VERIFY)
    ("Arudhra (MPR)", "LONG_RANGE", 300), ("Rohini (3D CAR)", "MEDIUM_POWER", 170),
    ("Ashwini (LLTR)", "LOW_LEVEL_TRANSPORTABLE", 200), ("Aslesha (LLLR)", "LOW_LEVEL_LIGHTWEIGHT", 50),
    ("THD-1955", "LONG_RANGE", 300), ("EL/M-2084", "MEDIUM_POWER", 250), ("Aerostat EL/M-2083", "AEROSTAT", 500),
]

FIRST = ("Aarav Aditi Akash Ananya Arjun Anjali Ayaan Bhavna Chirag Deepa Devansh Divya Farhan Gauri Harsh Ishita "
         "Kabir Kavya Karan Lakshmi Manav Meera Nikhil Neha Omkar Pallavi Pranav Priya Rahul Rhea Rohan Sana Siddharth "
         "Sneha Tanmay Tara Uday Vaishnavi Varun Zoya Abhay Amrita Bhaskar Chitra Dhruv Esha Gaurav Hema Imran Jaya "
         "Kunal Lavanya Mohit Nandini Nitin Pooja Rakesh Ritu Sahil Shruti Sunil Swati Tushar Uma Vikram Yamini Aniket "
         "Bhumika Charan Dipika Ganesh Ira Jatin Komal Lokesh Madhuri Naveen Ojasvi Parth Rashmi Saurabh Tanvi Vivek "
         "Yash Arnav Kiran Mihir Nisha Prateek Ruchi Shaurya Trisha Vedant Aisha Rehan Simran Gurpreet Harleen Jaspreet "
         "Lalit Manpreet Navneet Rupinder Thomas Anita Joseph Mary Wangchuk Pema Lalremruata Lalhriatpuii Bijoy Ritika "
         "Ashwin Keerthana Murugan Revathi Senthil Vasanth Akhil Athira Sreejith Anupama").split()
LAST = ("Sharma Verma Gupta Iyer Nair Menon Reddy Rao Naidu Patil Kulkarni Deshmukh Joshi Pandey Mishra Tiwari Dubey "
        "Chauhan Rathore Shekhawat Bhatia Malhotra Kapoor Khanna Sethi Grewal Sandhu Gill Dhillon Sidhu Bajwa Rana Thakur "
        "Negi Bisht Rawat Chauhan Mehta Shah Desai Parikh Trivedi Bhatt Dave Chatterjee Banerjee Mukherjee Ghosh Bose Das "
        "Sen Dutta Roy Saikia Gogoi Bora Barua Hazarika Kalita Singha Laishram Ngangom Lepcha Bhutia Tamang Chhetri "
        "Gurung Lama Fernandes D'Souza Pereira Rodrigues Thomas Mathew Varghese Kurian Pillai Krishnan Subramanian "
        "Raman Venkatesh Swaminathan Ansari Qureshi Siddiqui Khan Hussain Rizvi Mirza Shaikh Pathan Jadhav Pawar Shinde "
        "More Kadam Gaikwad Salunkhe Bhosale Yadav Ahirwar Meena Saini Jat Choudhary Bishnoi Panwar Tomar Bhardwaj Saxena").split()
CALLSIGNS = ("Talon Viper Cobra Falcon Hawk Raptor Saber Lancer Arrow Blaze Thunder Storm Shadow Ghost Phantom Wolf "
             "Tiger Panther Jaguar Lynx Raven Eagle Condor Kestrel Osprey Harrier Spartan Titan Atlas Zeus Apollo "
             "Orion Vega Rigel Nova Comet Meteor Bolt Spark Flint Steel Iron Granite Onyx Cobalt Rogue Maverick "
             "Ranger Nomad Hunter Archer Gunner Rider Striker Rapier Dagger Kukri Trishul Vajra Garuda Chakra Agni "
             "Vayu Indra Surya Prithvi Akash Tejas Shaurya Veer Yoddha Bheem Arjun Nakul Rudra Shiva Kali Durga "
             "Hanuman Ashwa Simha Nandi Mayur Hans Neel Megh Toofan Andhi Bijli").split()
# Notable real IAF names generated pilots must never collide with (extend freely).
DENYLIST = ["Arjan Singh", "Nirmal Jit Singh Sekhon", "Abhinandan Varthaman", "Rakesh Sharma", "Gunjan Saxena",
            "Avani Chaturvedi", "Bhawana Kanth", "Mohana Singh", "Vivek Ram Chaudhari", "Rakesh Kumar Singh Bhadauria",
            "Birender Singh Dhanoa", "Arup Raha", "Norman Anil Kumar Browne", "Pradeep Vasant Naik",
            "Fali Homi Major", "Shashindra Pal Tyagi", "Srinivasapuram Krishnaswamy", "Anil Yashwant Tipnis",
            "Amar Preet Singh", "Shivangi Singh", "Karambir Singh", "Subroto Mukerjee", "Idris Hasan Latif",
            "Pratap Chandra Lal", "Om Prakash Mehra", "Dilbagh Singh", "Lakshman Madhav Katre", "Denis La Fontaine",
            "Surinder Mehra", "Nirmal Chandra Suri", "Hrushikesh Moolgavkar", "Anil Kumar Tipnis",
            "Shalini Singh", "Avani Chaturvedi", "Kalpana Chawla", "Ajit Bhonsle", "Harish Masand"]


def rows(block):
    return [line.split("|") for line in block.strip().splitlines() if line.strip()]


def write(name, header, data):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    print(f"{name}: {len(data)} rows")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    oa = {}
    for r in csv.DictReader(open(RAW / "airports.csv", encoding="utf-8")):
        for k in ("ident", "icao_code", "gps_code"):
            if r[k]:
                oa.setdefault(r[k], r)

    def loc(ident):
        r = oa[ident]
        elev = round(float(r["elevation_ft"]) * 0.3048, 1) if r["elevation_ft"] else ""
        icao = r["icao_code"] or r["gps_code"] or ""
        return r["ident"], icao, r["iata_code"], float(r["latitude_deg"]), float(r["longitude_deg"]), elev, r["wikipedia_link"]

    hdr = ["ident", "icao", "iata", "name", "lat", "lon", "elevation_m", "command", "wing", "base_type", "role_tags",
           "size_class", "source_url", "verify"]
    data = []
    for ident, name, cmd, wing, btype, roles, size in rows(IAF_BASES):
        i, icao, iata, lat, lon, elev, wiki = loc(ident)
        data.append([i, icao, iata, name, lat, lon, elev, cmd, wing, btype, roles, size, wiki or WIKI_STATIONS, 1])
    for ident, name, cmd in rows(ALGS):
        i, icao, iata, lat, lon, elev, wiki = loc(ident)
        data.append([i, icao, iata, name, lat, lon, elev, cmd, "", "ALG", "ALG", "S", wiki or WIKI_STATIONS, 1])
    write("iaf_bases.csv", hdr, data)

    data = []
    for ident, name, op, notes in rows(OTHER_INDIAN_MIL):
        i, icao, iata, lat, lon, elev, wiki = loc(ident)
        data.append([i, icao, name, op, lat, lon, elev, notes, wiki or "https://ourairports.com/airports/" + i, 1])
    write("other_indian_mil.csv", ["ident", "icao", "name", "operator", "lat", "lon", "elevation_m", "public_notes",
                                   "source_url", "verify"], data)

    data = []
    for ident, iso3, op, notes in rows(NEIGHBOUR_BASES):
        i, icao, iata, lat, lon, elev, wiki = loc(ident)
        data.append([i, icao, notes, iso3, op, lat, lon, elev, notes, wiki or "https://ourairports.com/airports/" + i, 1])
    write("neighbour_bases.csv", ["ident", "icao", "name", "country_iso3", "operator", "lat", "lon", "elevation_m",
                                  "public_notes", "source_url", "verify"], data)

    data = [[n, nm, t, oa[b]["ident"], WIKI_STATIONS, 1] for n, nm, t, b in rows(SQUADRONS)]
    write("iaf_squadrons.csv", ["number", "name", "aircraft_type", "home_base_ident", "source_url", "verify"], data)

    write("aircraft_types.csv", ["name", "icao_type", "variant", "manufacturer", "category", "role", "seats_pilot",
                                 "seats_other", "max_fuel_kg", "burn_kg_per_h", "cruise_kt", "endurance_h",
                                 "combat_radius_km", "slot_size", "maint_interval_h", "turnaround_min",
                                 "serial_prefix", "sidc_function", "in_service", "target_fleet"],
          [r + [] for r in rows(AIRCRAFT_TYPES)])
    write("ad_system_types.csv", ["name", "category", "max_range_km", "max_alt_m"], AD_SYSTEMS)
    write("radar_types.csv", ["name", "category", "max_range_km"], RADARS)
    write("names_first.csv", ["first_name"], [[n] for n in sorted(set(FIRST))])
    write("names_last.csv", ["last_name"], [[n] for n in sorted(set(LAST))])
    write("callsign_words.csv", ["word"], [[w.upper()] for w in sorted(set(CALLSIGNS))])
    write("names_denylist.csv", ["full_name"], [[n] for n in sorted(set(DENYLIST))])
    for t in {r[2] for r in rows(SQUADRONS)} - {r[0] for r in rows(AIRCRAFT_TYPES)}:
        raise SystemExit(f"squadron references unknown aircraft type {t!r}")


if __name__ == "__main__":
    main()
