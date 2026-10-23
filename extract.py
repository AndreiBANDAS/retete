#!/usr/bin/env python3
"""Extract the recipes from Retete.pdf into recipes.json.

Usage: extract.py <pdf> <out.json>

Poppler's bbox layout gives word coordinates; every recipe page has a title, a
servings/time/calories strip, then a two-column body (ingredients left,
instructions right) and a lower block (macros left, tips right).
"""
import html
import json
import re
import subprocess
import sys

LINE_TOL = 3.5   # word baselines within this distance share a line
COL_GAP = 4      # gap before the right column's left edge
UNITS = r"(?:g|kg|ml|l|buc|bucăți|linguriță|linguri|lingură|căni|cană|felii|plăci)"

QTY = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*" + UNITS + r"\b")

# A few pages run several ingredients together in one flowed paragraph; the
# source text is unrecoverable by layout, so their lists are spelled out here.
FIXUPS = {
    85: ["600 g carne de vită extra slabă, tăiată cubulețe (ex. pulpă de vită, mușchi)",
         "20 g unt light", "6 căței de usturoi tocați fin",
         "200 ml supă de vită (sau apă cu concentrat slab de vită)",
         "90 g cremă de brânză light", "1 linguriță boia afumată",
         "1 linguriță pudră de supă de pui",
         "320 g paste integrale sau din grâu dur (penne, spirale, fusilli)",
         "Pentru sosul cremos de usturoi și parmezan:",
         "300 ml lapte semidegresat (1.5%)", "25 g parmezan ras proaspăt",
         "1 linguriță usturoi pudră", "1 linguriță oregano uscat",
         "½ linguriță piper negru"],
    92: ["700 g piept de pui tăiat cubulețe (fără os și piele)",
         "1 linguriță ulei de măsline", "1 linguriță sare", "1 linguriță pudră de ceapă",
         "1 linguriță pudră de usturoi", "1 linguriță boia afumată",
         "340 ml lapte evaporat (sau lapte 1.5% redus pe foc până se îngroașă puțin)",
         "80 g cremă de brânză light", "1½ linguriță pudră de supă de pui",
         "100 g cașcaval light ras", "320 g paste tip macaroane",
         "Pentru sosul de miere și usturoi:", "2 linguri miere", "1 lingură sos de soia",
         "1 linguriță oțet de orez sau zeamă de lămâie",
         "1–2 căței de usturoi dați pe răzătoare",
         "opțional: fulgi de chilli sau ghimbir ras"],
    116: ["2 avocado", "4 ouă", "rozmarin"],
    60: ["2.25 kg piept de pui (cuburi, fără piele/os)", "Condimente:",
         "1 linguriță sare", "1½ linguriță boia afumată", "1 linguriță usturoi pudră",
         "1 linguriță ceapă pudră", "1 linguriță mix ierburi italiene",
         "zeama de ½ lămâie", "Oregano uscat + pătrunjel uscat (pentru topping)",
         "6 căței usturoi tocați", "500 ml lapte evaporat light (sau 1.5% redus pe foc)",
         "80 g cremă de brânză light", "40 g parmezan ras", "100 g cașcaval light ras",
         "15 lipii mici/medii", "300 g mozzarella light rasă (≈20 g/lipie)"],
    141: ["Baza:", "40 g fulgi de ovăz", "100 ml apă",
          "50 g lapte 1.5% sau vegetal (ex. migdale, ovăz)", "1 praf de sare",
          "[Opțional] îndulcitor lichid sau stevia după gust", "După fierbere:",
          "150 g iaurt grecesc 2%", "15 g unt de arahide natural",
          "15 g lapte praf (sau pudră proteică vanilie/cacao – opțional)",
          "Pentru topping:", "20 g stevia sau 1 linguriță îndulcitor lichid pudră (sau 20 g miere)",
          "25 ml lapte", "15 g cacao pudră"],
    145: ["2 ouă întregi, 3 albușuri", "200 ml lapte 1.5%", "2 lingurițe cafea instant",
          "40 g cacao pudră neîndulcită",
          "250 g brânză cottage slabă (sau brânză de vaci granulată fin)",
          "150 g fulgi de ovăz", "5 g praf de copt", "2 g sare", "2 g esență de vanilie",
          "Crema:",
          "200 g iaurt grecesc (ex. Hercules sau alt iaurt cu gust neutru, nu acrișor)",
          "1 linguriță cafea instant",
          "Îndulcitor natural (stevia, eritritol) – după gust, dar dulce intens"],
}

TIPS = re.compile(r"^(Alergeni|Variante|Alternative|Trebuie|Poți|Se|Pentru|Alege|Dacă"
                  r"|Merge|Fără|Adaugă|Servește|Înlocuiește|Gust|Notă|Sfat)", re.I)


def run(args):
    return subprocess.run(args, capture_output=True, text=True, check=True).stdout


def words_of_page(pdf, page):
    xml = run(["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), pdf, "-"])
    return [{"x": float(x0), "y": float(y0), "x2": float(x1), "t": html.unescape(txt)}
            for x0, y0, x1, _, txt in re.findall(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>',
                xml)]


def to_lines(words):
    rows = []
    for w in sorted(words, key=lambda w: w["y"]):
        if rows and abs(rows[-1][0] - w["y"]) <= LINE_TOL:
            rows[-1][1].append(w)
        else:
            rows.append([w["y"], [w]])
    lines = []
    for y, ws in rows:
        ws.sort(key=lambda w: w["x"])
        cell, prev = [], None
        for w in ws:
            if prev is not None and w["x"] - prev > 45:
                lines.append((y, " ".join(x["t"] for x in cell)))
                cell = []
            cell.append(w)
            prev = w["x2"]
        lines.append((y, " ".join(x["t"] for x in cell)))
    return [(y, re.sub(r"\s+", " ", t).strip()) for y, t in lines]


def column_text(words, boundary, left):
    return to_lines([w for w in words if (w["x"] < boundary) == left])


def split_items(line):
    """Cut run-together ingredient lines at quantity boundaries (paren-aware)."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(line):
        c = line[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and i > start:
            m = QTY.match(line, i)
            if m:
                rest = line[m.end():].lstrip()
                # a quantity followed by a lowercase noun starts a new item
                before = re.sub(r"[^\w]+$", "", line[start:i])
                if (rest[:1].islower() and not before.endswith(("sau", "și", "cu", "de", "la"))
                        and not before.endswith(("-", "–"))):
                    out.append(line[start:i].strip(" ,"))
                    start, i = i, m.end()
                    continue
        i += 1
    out.append(line[start:].strip(" ,"))
    return [o for o in out if o]


def join_items(lines):
    """Split run-together lines at quantities, then rejoin wrapped fragments."""
    items = []
    for ln in lines:
        for part in split_items(ln):
            if items and (re.match(r"^[a-zăâîșț(]", part)
                          or re.search(r"\b(sau|și|cu|de|la)$", items[-1])
                          or items[-1].count("(") > items[-1].count(")")):
                items[-1] += " " + part
            else:
                items.append(part)
    return items


def parse_recipe(words):
    instr = next((w for w in words if w["t"].upper().startswith("INSTRUC")), None)
    if not instr:
        return None
    hdr_y = instr["y"]
    col = instr["x"] - COL_GAP
    macro_hdr = min([w["y"] for w in words if w["t"].upper().startswith("MACRO")] or [1e9])
    tips_hdr = min([w["y"] for w in words if w["t"].upper().startswith("SFATURI")] or [1e9])
    # the macro block sits under the left column, except on pages where it was
    # moved to the right one; there the ingredient list runs to the page bottom
    macro_left = any(w["t"].upper().startswith("MACRO") and w["x"] < col for w in words)
    left_cut = macro_hdr if macro_left else 1e9

    left = [(y, t) for y, t in column_text(words, col, True) if hdr_y + 1 < y < left_cut]
    right = [(y, t) for y, t in column_text(words, col, False) if hdr_y + 1 < y < tips_hdr]
    below = [(y, t) for y, t in column_text(words, col, False) if y >= tips_hdr]
    macro_rows = [(y, t) for y, t in column_text(words, col, True) if y >= macro_hdr]

    title = " ".join(w["t"] for w in sorted(words, key=lambda w: w["x"])
                     if hdr_y - 34 <= w["y"] < hdr_y - 4)
    stats = " ".join(t for _, t in to_lines([w for w in words if w["y"] < 40]))
    served = re.search(r"(\d+)\s*por[iț]", stats, re.I)
    mins = re.search(r"(\d+)\s*min", stats, re.I)
    kcal_top = re.search(r"(\d+)\s*calorii", stats, re.I)

    desc, steps = [], []
    for _, ln in right:
        if re.match(r"^\d+\.", ln):
            steps.append(ln)
        elif steps:
            if ln[:1].islower() or not steps[-1].endswith((".", ")", "!")):
                steps[-1] += " " + ln
            else:
                break
        else:
            desc.append(ln)
    steps = [re.sub(r"\s+", " ", re.sub(r"^\d+\.\s*", "", s)).strip() for s in steps]

    page_text = " ".join(w["t"] for w in words)

    def macro(label):
        m = re.search(label + r"\w*\s*:?\s*[~≈]?\s*([\d.]+)\s*(?:kcal|g)", page_text, re.I)
        return float(m.group(1)) if m else None

    kcal = macro("Calorii") or (int(kcal_top.group(1)) if kcal_top else None)
    parens = [m.group(1).strip() for m in
              (re.search(r"\(\s*([^)]*)\)", t) for _, t in macro_rows + below) if m]
    parens = [p for p in parens if not p.lower().startswith("din care")]
    portion = next((p for p in parens if re.search(r"\d\s*(?:g|gr|ml|buc)", p)),
                   parens[0] if parens else "")
    ingredients = join_items([t for _, t in left
                              if not re.match(r"^(C|P)alorii|^(Proteine|Carbohidra|Gr[ăa]simi"
                                              r"|MACRO|\(din care|\(~|\()", t)])
    blocks = []
    for _, t in below:
        if (blocks and not re.match(r"^(Alergeni|Variante|Alternative):", t, re.I)
                and (t[:1].islower() or not blocks[-1].endswith((".", ")", "!")))):
            blocks[-1] += " " + t
        else:
            blocks.append(t)
    tips = [b for b in blocks if TIPS.match(b) and "PRACTICE" not in b.upper()]
    # some pages print the steps again in the tips column; drop those echoes
    tips = [t for t in tips
            if not any(s.startswith(t[:30]) or t.startswith(s[:30]) for s in steps)]
    allergens = next((t.split(":", 1)[1].strip() for t in tips
                      if re.match(r"Alergeni:", t, re.I)), "")
    variants = next((t.split(":", 1)[1].strip() for t in tips
                     if re.match(r"(Variante|Alternative):", t, re.I)), "")

    return {
        "title": title.strip(),
        "servings": int(served.group(1)) if served else None,
        "minutes": int(mins.group(1)) if mins else None,
        "kcal": int(kcal) if kcal else None,
        "description": " ".join(desc).strip(),
        "ingredients": ingredients,
        "steps": steps,
        "portion": portion,
        "protein": macro("Proteine"),
        "carbs": macro("Carbohidra"),
        "fat": macro("Gr[ăa]simi"),
        "allergens": allergens,
        "variants": variants,
        "tips": [t for t in tips if not re.match(r"(Alergeni|Variante|Alternative):", t, re.I)],
    }


def is_recipe(words):
    joined = " ".join(w["t"] for w in words)
    return "INGREDIENTE" in joined and "INSTRUCȚIUNI" in joined


def chapter_title(pdf, page):
    lines = [l.strip() for l in run(["pdftotext", "-f", str(page), "-l", str(page),
                                     pdf, "-"]).splitlines() if l.strip()]
    return " ".join(l for l in lines[:2] if len(l) < 40)


def main(pdf, out):
    pages = {p: words_of_page(pdf, p) for p in range(1, 205)}
    recipe_pages = [p for p in pages if is_recipe(pages[p])]
    dividers = {p: chapter_title(pdf, p) for p in range(2, 205)
                if p not in recipe_pages and p + 1 in recipe_pages}

    recipes, warnings = [], []
    for page in recipe_pages:
        r = parse_recipe(pages[page])
        if not r:
            continue
        chapter = [d for d in dividers if d < page]
        r["page"] = page
        r["category"] = dividers[max(chapter)] if chapter else None
        if page in FIXUPS:
            r["ingredients"] = FIXUPS[page]
        recipes.append(r)
        missing = [k for k in ("servings", "minutes", "kcal", "protein", "carbs", "fat")
                   if r[k] is None]
        if missing or len(r["ingredients"]) < 3 or not r["steps"] or not r["title"]:
            warnings.append(f"p{page} {r['title'][:40]!r} ing={len(r['ingredients'])} "
                            f"steps={len(r['steps'])} missing={missing}")

    json.dump(recipes, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(recipes)} recipes -> {out}")
    print("\n".join(f"  {d}: {n}" for d, n in dividers.items()))
    print("\n".join(warnings) or "no warnings")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
