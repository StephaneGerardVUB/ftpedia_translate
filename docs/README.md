# Documentation — pipeline ft:pedia

Ce dossier documente les scripts et le template utilisés pour transformer un
numéro de la revue **ft:pedia** (PDF) en articles Markdown (allemand + français)
puis en PDF LaTeX.

## Vue d'ensemble

```
ftpedia-YYYY-N.pdf
        │  split_ftpedia.py
        ▼
output/ftpedia-YYYY-N/
    pdf/                 un PDF par article
    articles/<NN_titre>/
        <NN_titre>.md        texte allemand (Markdown)
        <NN_titre>.fr.md     traduction française (optionnelle)
        images/fig_XX.png    figures recollées
        <NN_titre>.tex       généré par md2latex.py
        <NN_titre>.pdf       PDF LaTeX compilé
```

## Fichiers

| Fichier | Rôle |
|---|---|
| `split_ftpedia.py` | PDF → PDF par article + Markdown + images (+ traduction) |
| `md2latex.py` | Markdown → LaTeX (classe `ftpedia`) + compilation PDF |
| `ftpedia_template/ftpedia.cls` | classe LaTeX reproduisant la maquette ft:pedia |
| `ftpedia_template/example.tex` | article-exemple minimal |
| `HANDOFF.md` (racine) | état du projet et reprise dans une nouvelle session |

Documentation détaillée :

- [`split_ftpedia.md`](split_ftpedia.md) — extraction et traduction.
- [`md2latex.md`](md2latex.md) — conversion Markdown → LaTeX.
- [`ftpedia-cls.md`](ftpedia-cls.md) — classe LaTeX et maquette.

## Démarrage rapide

```bash
# 1) Extraire un numéro (PDF par article + Markdown allemand + images)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf

# 2) Ajouter la traduction française (DeepL, avec plusieurs clés)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf --translate \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt

# 3) Convertir les Markdown en LaTeX et compiler les PDF
python3 md2latex.py --magazine ftpedia-2026-1 --limit 2
```

## Prérequis

- **Python** : `PyMuPDF` (`fitz`), `requests`, `Pillow`.
- **TeX** (pour `md2latex.py`) : XeLaTeX (ou LuaLaTeX), `fontspec`,
  `polyglossia`, `geometry`, `multicol`, `titlesec`, `fancyhdr`, `caption`,
  `listings`, `xcolor`, `graphicx`, `float`, `array`, `tabularx`, `longtable`,
  `ulem`, `enumitem`, `microtype`, `amsmath`, `hyperref`.
- **Polices** : Arial, Times New Roman, Courier New (ou Liberation en
  équivalent libre). Voir `ftpedia-cls.md`.
- **Césure allemande** : paquet `hyphen-german` / `texlive-hyphen-german`.
- **Clés API** (fichiers non versionnés) :
  - `azurekey.txt` pour Azure Translator ;
  - `deeplkey.txt`, éventuellement `deeplkey1.txt`… pour DeepL ;
  - `librekey.txt` (optionnel) pour LibreTranslate.

## Remarques générales

- Un dossier de sortie est créé **par numéro** : `output/<magazine>/`.
- Les `.fr.md` existants sont réutilisés : relancer la traduction ne traduit
  que ce qui manque (sauf `--force-translate`).
- Les images sont référencées relativement (`images/fig_XX.png`) et sont
  partagées entre les versions allemande et française.
