"""UN M49 country codes (the ones that show up in sulfur trade), the Gulf set, and the
six countries whose trade flows the dashboard breaks down."""
from __future__ import annotations

# M49 numeric code -> short name. Only the codes seen in HS-2503 sulfur trade.
M49: dict[int, str] = {
    # Gulf exporters
    784: "UAE", 682: "Saudi Arabia", 634: "Qatar", 414: "Kuwait", 48: "Bahrain",
    512: "Oman", 364: "Iran", 368: "Iraq", 887: "Yemen",
    # other big exporters
    124: "Canada", 842: "USA", 398: "Kazakhstan", 643: "Russia", 795: "Turkmenistan",
    392: "Japan", 410: "South Korea", 528: "Netherlands", 56: "Belgium", 250: "France",
    276: "Germany", 724: "Spain", 616: "Poland", 703: "Slovakia", 380: "Italy",
    # importers / destinations
    360: "Indonesia", 504: "Morocco", 699: "India", 76: "Brazil", 156: "China",
    484: "Mexico", 152: "Chile", 604: "Peru", 170: "Colombia", 32: "Argentina",
    862: "Venezuela", 218: "Ecuador", 214: "Dominican Rep.", 340: "Honduras",
    192: "Cuba", 558: "Nicaragua", 320: "Guatemala", 600: "Paraguay", 858: "Uruguay",
    710: "South Africa", 516: "Namibia", 834: "Tanzania", 24: "Angola", 818: "Egypt",
    324: "Guinea", 466: "Mali", 686: "Senegal", 504: "Morocco", 792: "Turkey",
    788: "Tunisia", 12: "Algeria", 800: "Uganda", 404: "Kenya", 231: "Ethiopia",
    540: "New Caledonia", 598: "Papua New Guinea", 36: "Australia", 554: "New Zealand",
    458: "Malaysia", 608: "Philippines", 704: "Vietnam", 764: "Thailand",
    702: "Singapore", 50: "Bangladesh", 586: "Pakistan", 144: "Sri Lanka",
    490: "Other Asia (Taiwan)",
    0: "World",
}

# Gulf origins that must physically transit (or sit beside) the Strait of Hormuz.
GULF: set[int] = {784, 682, 634, 414, 48, 512, 364, 368}

# The six countries the dashboard breaks down. flow: M = imports, X = exports.
TRADE_COUNTRIES: list[dict] = [
    {"name": "Indonesia", "reporter": 360, "flow": "M"},
    {"name": "Morocco", "reporter": 504, "flow": "M"},
    {"name": "India", "reporter": 699, "flow": "M"},
    {"name": "Brazil", "reporter": 76, "flow": "M"},
    {"name": "USA", "reporter": 842, "flow": "X"},
    {"name": "Canada", "reporter": 124, "flow": "X"},
]


def name(code: int) -> str:
    return M49.get(code, f"code {code}")


def is_gulf(code: int) -> bool:
    return code in GULF
