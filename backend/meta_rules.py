"""No-metacommentary migration rules (overview.md UI/UX Rules). Used ONLY by the one-time, idempotent data migration and
by the seed-source rewrite. It is NOT a runtime sanitizer: sources (seed.py, routes_demo.py, agreement.py,
routes_phase5.py) were edited directly so nothing new is generated with these labels."""
import re

RULES = [
    (re.compile(r"\s*\((?:fictional(?: sample data)?|sample(?: term)?|SAMPLE)\)", re.I), ""),
    (re.compile(r",\s*fictional\)", re.I), ")"),
    (re.compile(r"\bDemo [A-Za-z0-9]{2,12}\.\s+(?=\S)"), ""),  # "Demo ab12. Ridgeline..." clone prefix
    (re.compile(r"^Sample tax configuration:\s*", re.I), ""),
    (re.compile(r"^Sample (\w)", re.I), lambda m: m.group(1).upper()),
    (re.compile(r"Contractor Lic\. SAMPLE-0000"), "Contractor license: Not set"),
    (re.compile(r"\s*[-\u2013]\s*Contractor license: Not set"), ". Contractor license: Not set"),
    (re.compile(r"^(?:Illustrative sample|Sample contractor template)[^\n]*$", re.I), ""),
    (re.compile(r"^(?:Fictional sample data|Prototype - fictional sample data in the demo|PROTOTYPE - IN DEVELOPMENT)$", re.I), ""),
    (re.compile(r"\s*\(?\bmade-up data\b[^)]*\)?", re.I), ""),
]
BANNED = re.compile(r"PROTOTYPE|\(fictional\)|fictional sample|Illustrative sample|\(SAMPLE\)|Sample job|Demo session -|made-up data|"
                    r"Sample contractor template|\bfictional\b|\(sample\)|\(sample term\)", re.I)


def clean_text(s: str) -> str:
    out = s
    for rx, rep in RULES:
        out = rx.sub(rep, out)
    return out.strip() if out != s else s
