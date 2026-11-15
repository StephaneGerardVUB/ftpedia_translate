# `md2latex.py` — conversion Markdown → LaTeX

## Rôle

Convertit les articles Markdown produits par `split_ftpedia.py` en documents
LaTeX utilisant la classe `ftpedia` (`ftpedia_template/ftpedia.cls`), puis les
compile en PDF avec **XeLaTeX**.

Les versions allemandes (`.md`) et françaises (`.fr.md`) sont prises en charge ;
la langue de la classe est choisie automatiquement.

## Utilisation

```bash
# Premiers N articles d'un numéro (allemand + français), avec compilation
python3 md2latex.py --magazine ftpedia-2026-1 --limit 2

# Fichiers précis
python3 md2latex.py --md output/ftpedia-2025-2/articles/03_*/*.md

# Allemand seulement, sans compiler
python3 md2latex.py --magazine ftpedia-2025-2 --limit 3 --no-fr --no-compile
```

## Options

| Option | Défaut | Description |
|---|---|---|
| `--magazine` | aucun | Nom du dossier du numéro sous `--out`. |
| `--out` | `output` | Racine où se trouvent les numéros. |
| `--md` | aucun | Liste de fichiers Markdown à convertir (alternative à `--magazine`). |
| `--limit` | aucun | Ne traite que les N premiers articles. |
| `--no-fr` | désactivé | Ignore les `.fr.md`. |
| `--dpi` | `300` | DPI utilisé lors du rendu des images (pour retrouver leur taille physique). |
| `--issue` | déduit du chemin | Force le numéro (`YYYY-N`) pour l'en-tête. |
| `--no-compile` | désactivé | Écrit seulement les `.tex` (pas de PDF). |

## Sorties

Pour chaque document source, à côté du `.md` :

- `<nom>.tex` / `<nom>.fr.tex` ;
- `<nom>.pdf` / `<nom>.fr.pdf` (sauf `--no-compile`).

En cas de succès, les fichiers auxiliaires (`.aux`, `.log`, `.out`) sont
supprimés.

## Correspondances Markdown → LaTeX

| Markdown | LaTeX |
|---|---|
| `# Titre` | `\titel{…}` |
| `**Kategorie:**` / `**Catégorie :**` | `\rubrik{…}` |
| `**Autor:**` / `**Auteur :**` | `\autor{…}` |
| `> …` (chapô) | environnement `ftabstract` |
| `## …` | `\section{…}` |
| `### …` | `\subsection{…}` |
| `![…](images/x.png)` | `figure` + `\includegraphics` |
| ligne `Abb.`/`Fig.`/`Tab.`/`Tableau` après une image/table | `\caption*{…}` |
| `\| … \|` | `tabularx` (ou `longtable` si > 25 lignes) |
| `- item` | `itemize` |
| `1. item` | `enumerate` |
| bloc de code (fenced) | `lstlisting` |
| `$$ … $$` | `\[ … \]` |
| `**gras**` | `\textbf{…}` |
| `*italique*` | `\emph{…}` |
| `***gras-italique***` | `\textbf{\emph{…}}` |
| code inline | `\texttt{…}` |
| `[texte](url)` | `\ftpediahref{url}{texte}` (bleu souligné) |
| `[^n]` | `\footnote{…}` (définition collectée en fin de document) |

L'échappement LaTeX des caractères spéciaux (`& % $ # _ { } ~ ^ \`) est
appliqué au texte, au code inline et aux URL.

## Notes de bas de page

Les définitions `[^n]: …` sont retirées du corps du document, puis injectées
au point d'appel sous forme de `\footnote{…}`.

## Images

- La largeur physique d'origine est déduite de la largeur du PNG et du `--dpi` :
  `largeur_pt = largeur_px × 72 / dpi`.
- Une image est considérée **pleine largeur** au-delà d'environ 300 pt ; elle est
  alors placée hors des colonnes (fermeture/réouverture de `multicols`).
- Les petites images conservent leur taille relative (icônes non agrandies).
- La hauteur est plafonnée (`0.9\textheight`, proportions conservées).

## Tableaux

- Les lignes `| … |` sont converties en `tabularx` pleine largeur.
- L'en-tête (première ligne) est mis en gras, les lignes sont séparées par des
  filets.
- Au-delà de 25 lignes de données, un `longtable` est utilisé pour permettre
  la coupure entre pages (en-tête répété).
- Les légendes de tableaux sont placées via `\caption*`.

## Maths

- Chaque ligne `$$ … $$` devient `\[ … \]`.
- Le contenu est déjà du LaTeX (produit par `split_ftpedia.py`) : fractions,
  racines, exposants, `\tag{n}` sont conservés tels quels.
- Les mots traduits à l'intérieur d'une formule sont déjà encadrés par
  `\text{…}` (voir `docs/split_ftpedia.md`).
- Les symboles Unicode (lettres grecques, `∆`, `×`, `≈`, `→`, `°`…) sont
  convertis en commandes LaTeX : les polices mathématiques Computer Modern
  n'ont pas ces glyphes et le caractère disparaîtrait silencieusement.
- Les lettres italiques mathématiques (`U+1D400…U+1D7FF`, p. ex. `𝑛`, `𝑝`) sont
  ramenées à des lettres ASCII, et les artefacts d'extraction (flèches de
  vecteur étirées, grands délimiteurs) sont neutralisés : sans cela, ils
  apparaissent comme des caractères manquants dans le PDF.
- La police mathématique reste celle de TeX (Computer Modern) pour l'instant.

## Langue

- Un fichier se terminant par `.fr.md` est compilé avec
  `\documentclass[french]{ftpedia}` ; sinon `german`.
- Le numéro d'en-tête (`Heft`/`Numéro`) et les libellés de légendes suivent la
  langue.

## Compilation

- Moteur : `xelatex -interaction=nonstopmode -halt-on-error`, deux passes.
- `TEXINPUTS` inclut `ftpedia_template/` pour trouver `ftpedia.cls`.

## Limites connues

- Les captures situées dans des cellules de tableaux restent des figures
  séparées.
- Un grand tableau découpé en plusieurs tableaux Markdown produit plusieurs
  tableaux LaTeX successifs.
- Les notes dans les cellules de tableaux ne sont pas traitées finement.
- Les très longs tableaux et les images pleine largeur peuvent modifier
  localement l'équilibrage des colonnes.
