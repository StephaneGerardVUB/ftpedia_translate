# ft:pedia — état du projet (handoff)

Ce fichier permet de reprendre le travail dans une nouvelle session opencode,
dans le même répertoire.

## Environnement

- Fedora Linux 43, Python 3.14.
- Python : `PyMuPDF` (fitz), `requests`, `Pillow`.
- TeX : XeLaTeX/LuaLaTeX, `fontspec`, `polyglossia`, `tabularx`, `longtable`,
  `ulem`, `caption`, `fancyhdr`, `listings`.
- Polices installées : **Arial, Times New Roman, Courier New** (paquet
  `msttcore-fonts-installer`) ; césure allemande via `texlive-hyphen-german`.
- Clés API (ne pas committer) :
  - `azurekey.txt` : Azure Translator — renvoie actuellement **401/401001**
    (clé invalide/expirée), donc inutilisable.
  - `deeplkey.txt` + `deeplkey1.txt` : DeepL Free. La 1re clé peut être
    épuisée ; le script bascule automatiquement sur la suivante.

## Fichiers

- `split_ftpedia.py` : PDF → PDF par article + `.md` allemand + images,
  traduction optionnelle `.fr.md`.
- `md2latex.py` : `.md` → `.tex` + PDF via `ftpedia_template/ftpedia.cls`.
- `ftpedia_template/ftpedia.cls` : classe LaTeX (maquette ft:pedia).
- `ftpedia_template/example.tex` / `.pdf` : exemple.
- `ftpedia-2025-1.pdf` … `ftpedia-2026-3.pdf` : 7 numéros sources.
- `output/<magazine>/` : résultats par numéro.
- `docs/` : documentation Markdown (`README.md`, `split_ftpedia.md`,
  `md2latex.md`, `ftpedia-cls.md`).

## Structure de sortie

```
output/<magazine>/
    pdf/                     # 1 PDF par article
    articles/<NN_titre>/
        <NN_titre>.md        # allemand
        <NN_titre>.fr.md     # français (si traduit)
        images/fig_XX.png
        <NN_titre>.tex       # généré par md2latex.py
        <NN_titre>.pdf       # PDF LaTeX compilé
```

## split_ftpedia.py — fonctionnalités

- Découpage via les signets de niveau 1 (`--min-page 4` par défaut).
- Ordre de lecture 2 colonnes ; recollage des paragraphes coupés par saut de
  page, changement de colonne ou illustration.
- Images : recollage des tuiles contiguës, rendu à `--dpi` (300 par défaut).
- Tableaux texte → tableaux Markdown.
- Listes à puces et numérotées (`-`, `1.`).
- Code (police Courier) → blocs ``` ; code inline en backticks ; commentaires
  `//` coupés par la colonne recollés.
- Gras / italique / gras-italique inline.
- Liens URI → `[texte](url)`.
- Notes de bas de page → `[^n]` + définitions `[^n]:`.
- Maths (CambriaMath) → LaTeX `$$ … $$` (fractions, racines via vinculum,
  exposants, `\tag{n}`), détection tolérante aux blocs mixtes. Les mots en
  clair des formules sont traduits et placés dans `\text{…}`.
- Métadonnées catégorie/auteur (lignes `**Kategorie:**`, `**Autor:**`).
- Titre : appariement robuste TOC/PDF (`title_key`).
- Traduction : `--translate --engine {azure,deepl,argos,libre}` ;
  DeepL multi-clés ; protection de la syntaxe Markdown ; quota géré.
- `--translate-only` : traduire les `.md` existants sans refaire PDF/images.

Commandes utiles :

```bash
# extraire un numéro (allemand seul)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf

# extraire + traduire en français (DeepL, 2 clés)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf --translate \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt

# traduire plus tard les .md existants
python3 split_ftpedia.py --translate-only --name ftpedia-2026-1 \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt
```

## md2latex.py — fonctionnalités

- Convertit les `.md` allemands et `.fr.md` (langue de classe automatique).
- Compile avec XeLaTeX (2 passes) et écrit le PDF à côté du `.tex`.
- Gère : métadonnées, chapô, sections, paragraphes (échappement LaTeX),
  gras/italique/code inline, liens (`\ftpediahref` bleu souligné), listes,
  code (`lstlisting`), tableaux (`tabularx`, `longtable` si >25 lignes),
  maths `\[…\]`, notes (`\footnote`), images (largeur relative au DPI),
  légendes `\caption*`, figures/tableaux pleine largeur (bascule multicols).
- Symboles Unicode des formules (grecques, ∆, ×, ≈, →, °…) convertis en
  commandes LaTeX : les polices mathématiques CM n'ont pas ces glyphes.

Commandes :

```bash
python3 md2latex.py --magazine ftpedia-2026-1 --limit 2
python3 md2latex.py --md output/ftpedia-2025-2/articles/03_*/*.md
python3 md2latex.py --magazine ftpedia-2025-2 --limit 3 --no-fr
```

## Template ftpedia.cls — points clés

- A4, 2 colonnes, marges 25 mm, colonne 12 mm.
- Arial (titres) / Times New Roman (corps) / Courier New (code).
- En-tête : pages impaires = logo à gauche, catégorie à droite ; pages paires
  = « Heft n/YYYY » (ou « Numéro » en français) à gauche, logo à droite.
- Logo : `f` rouge, `t` bleu, `:pedia` gris clair (RGB 165,165,165), sans
  espace avant `:` en français (espacement inter-caractères désactivé).
- Pied de page : filet horizontal + numéro à gauche si pair, à droite si impair.
- Légendes de figures centrées ; légendes de tableaux à gauche.
- Liens hypertextes bleus et soulignés.
- Langue : `\documentclass{ftpedia}` (allemand), `[french]`, `[english]`.

## État actuel

- 8 numéros extraits (PDF par article, `.md`, `.fr.md`, images) :
  2024-4 (12), 2025-1 (9), 2025-2 (9), 2025-3 (6), 2025-4 (18), 2026-1 (11),
  2026-2 (10), 2026-3 (6).
- `md2latex.py` testé sur 3 articles (DE + FR) :
  - `2026-1/01` Sphero BB-8 (images, listes)
  - `2025-2/03` Schräge Drehscheibe (maths, `\tag`, racines)
  - `2025-2/08` Oxocard (code, longs tableaux, 45 images)
  → 6 PDF compilés.
- `2024-4` extrait + traduit intégralement (12 articles, DeepL).

## Limites connues

- Tableaux « composites » (captures dans les cellules) : les images restent des
  figures séparées (la conversion en image unique a été annulée volontairement).
- Un grand tableau découpé en plusieurs tableaux Markdown (sauts de page)
  produit plusieurs tableaux LaTeX successifs.
- Maths en Computer Modern (police libre) ; choix d'une police math définitive
  reporté (pas de police Microsoft).
- Notes de bas de page dans les cellules de tableaux non traitées finement.
- Si les `.md` sont régénérés après modification de `split_ftpedia.py`, il faut
  retraduire les articles concernés (coût API).

## Prochaines étapes possibles

1. Choisir une police math libre (ex. TeX Gyre Termes Math via `unicode-math`).
2. Convertir plus d'articles / des numéros complets avec `md2latex.py`.
3. Améliorer les tableaux composites et la fusion des tableaux coupés.
4. Vérifier visuellement quelques PDF, puis généraliser.

## Astuce : limite « Too many images in request »

Le fournisseur du modèle limite le nombre d'images par requête (30). Chaque
image affichée via `read` reste dans l'historique de la session. Pour éviter
l'erreur :

- privilégier les vérifications **textuelles** (`pdftotext`, `pdffonts`,
  extraction de texte, tailles/dimensions, `grep`) plutôt que d'ouvrir des PNG ;
- n'ouvrir une image que si c'est indispensable, et peu à la fois ;
- démarrer une **nouvelle session** avant d'atteindre la limite (le travail est
  sur disque ; repartir de ce fichier).
