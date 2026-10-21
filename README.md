# ftpedia_translate

Outils Python pour transformer un numéro de la revue **ft:pedia** (PDF) en
articles Markdown — allemand puis français — et en PDF LaTeX.

Le dépôt contient deux scripts et une classe LaTeX qui reproduit la maquette de
la revue :

| Élément | Rôle |
|---|---|
| `split_ftpedia.py` | découpe un PDF en articles, extrait le Markdown, les images et les métadonnées ; traduction optionnelle |
| `md2latex.py` | convertit les Markdown en LaTeX (classe `ftpedia`) et compile les PDF |
| `ftpedia_template/` | classe LaTeX `ftpedia.cls` + article-exemple |
| `docs/` | documentation détaillée |
| `HANDOFF.md` | état du projet / reprise du travail |

## Pipeline

```
ftpedia-YYYY-N.pdf
        │  split_ftpedia.py
        ▼
output/ftpedia-YYYY-N/
    pdf/                 un PDF par article
    articles/<NN_titre>/
        <NN_titre>.md        texte allemand
        <NN_titre>.fr.md     traduction française (optionnelle)
        images/fig_XX.png
        <NN_titre>.tex       généré par md2latex.py
        <NN_titre>.pdf       PDF LaTeX compilé
```

## Démarrage rapide

```bash
# 1) Extraction d'un numéro (PDF par article + Markdown + images)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf

# 2) Traduction française (DeepL, plusieurs clés possibles)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf --translate \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt

# 3) Conversion Markdown -> LaTeX et compilation PDF
python3 md2latex.py --magazine ftpedia-2026-1 --limit 2
```

## Prérequis

- Python : `PyMuPDF` (`fitz`), `requests`, `Pillow`.
- TeX : XeLaTeX, `fontspec`, `polyglossia`, `tabularx`, `longtable`, `ulem`,
  `caption`, `fancyhdr`, `listings`, `hyperref`, etc.
- Polices : Arial, Times New Roman, Courier New (ou Liberation équivalent).
- Césure allemande : `hyphen-german` / `texlive-hyphen-german`.
- Clés API (non versionnées) : `azurekey.txt` (Azure) et/ou `deeplkey*.txt`
  (DeepL), éventuellement `librekey.txt` (LibreTranslate).

## Documentation

- [`docs/README.md`](docs/README.md) — vue d'ensemble et démarrage.
- [`docs/split_ftpedia.md`](docs/split_ftpedia.md) — extraction et traduction.
- [`docs/md2latex.md`](docs/md2latex.md) — conversion Markdown → LaTeX.
- [`docs/ftpedia-cls.md`](docs/ftpedia-cls.md) — classe LaTeX et maquette.

## Sécurité

Les clés API, les PDF sources (`ftpedia-*.pdf`) et les résultats (`output/`)
sont exclus du dépôt par `.gitignore`. Ne commitez jamais de clé.
