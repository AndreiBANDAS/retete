# Rețete

120 de rețete extrase din *120 de Rețete Sănătoase* (Bogdan Tîrziu, 2025) și
transformate într-o pagină statică: căutare după nume, filtrare pe categorie și
pe ingredient, plus valorile nutriționale pe porție.

Pagină: `index.html` · Date: `retete.json`

## Cum rulezi local

```bash
python3 -m http.server 8123
# http://localhost:8123
```

Pagina citește `retete.json` prin `fetch`, deci are nevoie de un server; deschisă
direct cu `file://` nu funcționează.

## Cum regenerezi datele

```bash
python3 extract.py /cale/catre/Retete.pdf retete.json
```

`extract.py` folosește `pdftotext -bbox-layout` (poppler) ca să citească
coordonatele cuvintelor și reconstruiește fiecare rețetă din cele două coloane
ale paginii: ingrediente în stânga, instrucțiuni în dreapta. Nu are nevoie de
OCR — PDF-ul are text selectabil.

La finalul rulării afișează rețetele cu câmpuri lipsă, ca să poți verifica.
Trei pagini au ingredientele scrise într-un singur paragraf în original și sunt
completate manual în `FIXUPS`.

## Structura datelor

`retete.json` este o listă de obiecte, în ordinea din carte:

| câmp | tip | exemplu |
|---|---|---|
| `title` | string | `"SALATĂ DE BOEUF LIGHT"` |
| `category` | string | `"Aperitive și gustări fresh"` |
| `page` | number | `50` — pagina din PDF, pentru verificare |
| `servings` | number | `6` |
| `minutes` | number | `50` |
| `kcal` | number | `165` |
| `protein`, `carbs`, `fat` | number | `17`, `11`, `6` (grame pe porție) |
| `portion` | string | `"~200 g"` |
| `description` | string | textul de sub titlu |
| `ingredients` | string[] | o linie per ingredient; liniile care se termină cu `:` sunt subtitluri de grup |
| `steps` | string[] | pașii, fără numerotare |
| `allergens` | string | `"ouă, muștar, lactoză (din iaurt)."` |
| `variants` | string | sugestii de înlocuire |
| `tips` | string[] | sfaturi din coloana din dreapta |

Câmpurile care lipsesc în original sunt `""` sau `null`, niciodată inventate.

## Surse și limite

- Textul, structura și valorile nutriționale aparțin autorului și editurii.
  Pagina este o copie personală, neindexată, cu atribuire.
- Imaginile din carte nu au fost extrase.
- Extragerea automată a rețetelor a fost verificată manual; cele patru rețete cu
  probleme sunt corectate explicit în `extract.py`.
