"""Shared rules: violation severity, plain-English phrases, pest evidence, and the rule-based summary.

The rule-based summary is the no-AI fallback: every inspection with violations gets one, built only from
fields the inspector filled in (result, violation numbers, severity wording, a few key phrases in the notes).
It never invents details; an AI summary replaces it when one exists.
"""
import re

import pandas as pd

# Evidence words, not verbs: "OVER 50 MICE DROPPINGS" has no "observed"; "RODENT TRAP DEVICES" is not evidence.
PEST_SEEN = r"DROPPING|\bLIVE\b|\bDEAD\b|CARCASS|INFEST|ROACHES|\bGNATS\b|\bFLIES\b|NESTING|GNAWED|RUB MARKS"
# Closure = the city actually shut the place or suspended its license. No bare "CLOSURE" or "CLOSED BY": in 3 years of notes
# those matched ~800 inspections and none was a shutdown ("menu DISCLOSURE", "dumpster LID CLOSURE", "door held CLOSED BY rope").
CLOSURE = r"SUMMARILY SUSPENDED|SUMMARY SUSPENSION|LICENSE (?:WAS |IS )?SUSPENDED|CEASE AND DESIST|ESTABLISHMENT CLOSED|CLOSED BY (?:THE )?(?:CITY|CDPH|DEPARTMENT|INSPECTOR)"
SEV_ORDER = {"priority": 0, "priority_foundation": 1, "risk_factor": 2, "core": 3, "upkeep": 4}

# Plain words for each violation number (as a problem found, not the rule's title).
PLAIN = {1: "No one in charge knew food safety rules", 2: "No certified food manager on site",
         3: "Sick-worker policy missing", 4: "Sick worker not kept from food", 5: "No plan for vomit/diarrhea cleanup",
         6: "Eating, drinking or smoking in food areas", 7: "Worker with runny eyes or nose handling food",
         8: "Hands not washed properly", 9: "Bare-hand contact with ready-to-eat food",
         10: "Hand sink not usable or stocked", 11: "Food from an unapproved source",
         12: "Food delivered at unsafe temperatures", 13: "Raw and ready-to-eat food not kept apart",
         14: "Required food records missing", 15: "Food not separated or protected",
         16: "Dishes or surfaces not properly sanitized", 17: "Returned or unsafe food not discarded",
         18: "Food not cooled properly", 19: "Food not reheated properly", 20: "Hot food not kept hot enough",
         21: "Hot food not kept hot enough", 22: "Cold food not kept cold enough", 23: "Food missing discard dates",
         24: "Time-based food safety not followed", 25: "Consumer advisory missing",
         26: "Prohibited or unpasteurized food", 27: "Unapproved food additives",
         28: "Chemicals not labeled or stored safely", 29: "Special process without approval",
         30: "Unpasteurized eggs used", 31: "Water or ice from an unapproved source",
         32: "Special process without approval", 33: "Food not thawed or cooled correctly",
         34: "Plant food not cooked properly", 35: "Food not thawed correctly", 36: "Thermometers missing",
         37: "Food not labeled", 38: "Pest problems", 39: "Food not protected from contamination",
         40: "Staff hair or hygiene issues", 41: "Wiping cloths not stored properly",
         42: "Produce not washed", 43: "Utensils not stored properly", 44: "Utensils or equipment stored poorly",
         45: "Single-use items not stored properly", 46: "Gloves not used properly",
         47: "Equipment in poor repair", 48: "Dishwashing setup not working right", 49: "Surfaces not clean",
         50: "Hot or cold water problems", 51: "Plumbing problems", 52: "Sewage or waste water problems",
         53: "Restroom not clean or stocked", 54: "Garbage area problems", 55: "Facility not clean or maintained",
         56: "Ventilation or lighting problems", 57: "Staff missing food handler training",
         58: "Allergen training missing", 59: "Earlier problems not fixed", 60: "Earlier problems not fixed",
         61: "Earlier problems not fixed", 62: "Smoking indoors", 63: "Suspension sign removed",
         64: "Public health order issue"}


def severity(vio: pd.DataFrame) -> pd.Series:
    """What the inspector wrote ("PRIORITY", "PRIORITY FOUNDATION", "CORE"); unlabeled 1-29 = risk factor, 30+ = upkeep."""
    c = vio.comment.fillna("").str.upper()
    sev = pd.Series(pd.NA, index=vio.index, dtype="object")
    sev[c.str.contains(r"\bCORE\b")] = "core"
    sev[c.str.contains(r"PRIORITY\s+FOUNDATION|\bPF\b")] = "priority_foundation"
    sev[c.str.contains(r"PRIORITY\s+VIOLATION|PRIORITY\.|PRIORITY\s*\(P\)|\(P\)") & ~c.str.contains(r"PRIORITY\s+FOUNDATION")] = "priority"
    return sev.fillna(vio.number.map(lambda n: "risk_factor" if n <= 29 else "upkeep"))


def pest_phrase(text: str) -> str:
    """'About 65 rodent droppings and 15 flies found': counts the inspector wrote are added up across spots."""
    t = text.upper()
    found = []
    for word, label in ((r"(?:COCK)?ROACH(?:ES)?", "roaches"), (r"(?:MICE|MOUSE|RODENT|RAT)S?\s+DROPPINGS?", "rodent droppings"),
                        (r"\bMICE\b|\bMOUSE\b|\bRATS?\b|\bRODENTS?\b(?!\s+(?:DROPP|ENTRY|PROOF|ACTIVITY|HARBOR))", "rodents"),
                        (r"\bFLIES\b|\bFLY\b|GNATS?", "flies")):
        if not re.search(word, t) or (label == "rodents" and any("rodent droppings" in f for f in found)):
            continue
        nums = re.findall(r"(OVER |APPROX(?:IMATELY)?\.? |ABOUT )?(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*\+?\s+(?:[A-Z]+\s+){0,3}?(?:" + word + ")", t)
        n = sum(int(hi or lo) for _, lo, hi in nums)
        approx = len(nums) > 1 or any(q.strip().startswith(("APPROX", "ABOUT")) or hi for q, _, hi in nums)
        over = len(nums) == 1 and nums[0][0].startswith("OVER")
        found.append(label)
        if n > 1:
            found[-1] = f"{'over ' if over else 'about ' if approx else ''}{n} {label}"
    if not found:
        return "Signs of pests found"
    s = " and ".join(found[:2])
    return s[0].upper() + s[1:] + " found"


RESULT = {"Fail": "Failed", "Pass w/ Conditions": "Passed with conditions", "Pass": "Passed"}


def _temps(c: str) -> list:
    return re.findall(r"(\d{2,3}(?:\.\d)?)\s*(?:F\b|DEGREES)", c.upper())[:2]


def rule_summary(itype: str, result: str, vg: pd.DataFrame) -> dict:
    """vg: this inspection's violation rows with number, comment, sev. Returns headline / summary / pests."""
    vg = vg.assign(c=vg.comment.fillna("").str.upper())
    vg = vg.assign(pest=(vg.number == 38) & vg.c.str.contains(PEST_SEEN, regex=True))
    vg = vg.assign(o=vg.sev.map(SEV_ORDER) - vg.pest * 10).sort_values(["o", "number"])
    items, pri = [], 0
    for x in vg.itertuples():
        if x.number == 38:   # all pest-evidence notes become one phrase, counts added up
            p = pest_phrase(" ".join(vg[vg.pest].c)) if x.pest else "Gaps or conditions that could let pests in"
        else:
            p = PLAIN.get(int(x.number), "Other violation")
            if x.number in (18, 19, 20, 21, 22, 33) and _temps(x.c):
                p += " (" + ", ".join(t + "°F" for t in _temps(x.c)) + ")"
        if p not in items:
            items.append(p)
            pri += x.sev == "priority"
    allc = " ".join(vg.c)
    head = items[0] if len(items) == 1 or len((items[0] + items[1]).split()) > 9 else f"{items[0]}; {items[1][0].lower() + items[1][1:]}"
    why = (" after a complaint" if "COMPLAINT" in itype.upper() else
           " on re-inspection" if "RE-INSPECTION" in itype.upper() else "")
    n = len(items)   # distinct problems (inspectors often cite the same item twice)
    listed = ", ".join(i[0].lower() + i[1:] for i in items[:4]) + (f", and {len(items) - 4} more" if len(items) > 4 else "")
    body = f"{RESULT.get(result, result)}{why}. {n} issue{'s' if n != 1 else ''}"
    body += (f" ({pri} priority)" if pri else "") + f": {listed}."
    extra = []
    if re.search(CLOSURE, allc): extra.append("closure or license suspension noted")
    if any(re.search(r"CITATIONS? (?:WAS |WERE )?ISSUED", c) and not re.search(r"NO CITATION", c) for c in vg.c):
        extra.append("citation issued")
    if re.search(r"DISCARD|DENATURED|DISPOSED OF|VOLUNTARILY", allc): extra.append("some food thrown out")
    if re.search(r"HELD FOR INSPECTION|PLACED ON HOLD|TAGGED", allc): extra.append("food or equipment put on hold")
    if re.search(r"CORRECTED ON SITE|CORRECTED DURING|\bCOS\b|VIOLATION CORRECTED", allc): extra.append("some issues fixed on the spot")
    if extra:
        s = "; ".join(extra)
        body += " " + s[0].upper() + s[1:] + "."
    return {"headline": head, "summary": body, "pests": bool(vg.pest.any())}
