"""Search Wikimedia Commons for rights-cleared tie/fastener photos; writes candidates.json (metadata only, no downloads)."""
import json, re, sys, time
import requests

UA = {"User-Agent": "RailReadyEvalBuilder/1.0 (image eval set; contact: builder@railready.example) requests"}
API = "https://commons.wikimedia.org/w/api.php"
QUERIES = [
    "rotten railroad tie", "railroad tie plate spike", "wooden railway sleeper rot", "railroad ties weathered",
    "tie plate cut spike", "railroad spike missing", "split railroad tie", "crosstie track United States",
    "railroad track wooden ties close up", "spike holes railroad tie", "Pandrol clip wooden sleeper",
    "screw spike railroad", "rail anchor tie plate", "railroad track ballast covered ties", "railroad track shadow ties",
    "abandoned railroad track ties", "railroad track vegetation overgrown ties",
]
OK = re.compile(r"^(CC0|Public domain|PD.*|CC BY(-SA)? ?[0-9.]+.*|CC-BY(-SA)?-[0-9.]+)$", re.I)


def strip(h):
    return re.sub(r"<[^>]+>", "", h or "").strip()


