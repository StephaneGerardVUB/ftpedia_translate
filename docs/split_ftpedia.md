# `split_ftpedia.py` — extraction d'un numéro ft:pedia

## Rôle

Découpe un PDF de la revue **ft:pedia** en articles, puis extrait pour chaque
article :

1. un **PDF autonome** (pages de l'article) ;
2. un **Markdown allemand** (texte, images, tableaux, listes, notes, formules) ;
3. les **images** dans `images/` (figures recollées) ;
4. optionnellement, une **traduction** `<article>.<lang>.md`.

Le script utilise la table des matières (signets de niveau 1) pour délimiter
les articles.

## Utilisation

```bash
# Le PDF du dossier (avertit s'il y en a plusieurs)
python3 split_ftpedia.py

# PDF explicite
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf

# Extraction + traduction française via DeepL (deux clés, bascule auto)
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf --translate \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt

# Traduction différée : ne traduit que les .md existants
python3 split_ftpedia.py --translate-only --name ftpedia-2026-1 \
    --engine deepl --deepl-key deeplkey.txt deeplkey1.txt

# Autre langue cible
python3 split_ftpedia.py --pdf ftpedia-2026-1.pdf --translate --to en
```

## Options

| Option | Défaut | Description |
|---|---|---|
| `--pdf` | seul `*.pdf` du dossier | PDF source. |
| `--out` | `output` | Racine de sortie. |
| `--name` | nom du PDF | Nom du dossier du numéro (tirets conservés). |
| `--min-page` | `4` | Première page (1-based) considérée comme article (ignore couverture/édito/sommaire). |
| `--dpi` | `300` | Résolution de rendu des figures recollées. |
| `--math-engine` | `heuristic` | `auto`, `heuristic` ou `pix2tex`. |
| `--translate` | désactivé | Produit les traductions. |
| `--translate-only` | désactivé | Traduit les `.md` existants sans refaire PDF/images. |
| `--engine` | `azure` | `azure`, `deepl`, `argos`, `libre`. |
| `--to` | `fr` | Langue cible. |
| `--force-translate` | désactivé | Retraduit même si le fichier existe. |
| `--azure-params` | aucun | Fichier de paramètres Azure optionnel (`endpoint`, `location`, `to_lang`). |
| `--azure-key` | `azurekey.txt` | Clé Azure. |
| `--deepl-key` | `deeplkey.txt` | Un ou plusieurs fichiers de clé DeepL (bascule auto). |
| `--libre-url` | aucun | Endpoint LibreTranslate. |
| `--libre-key` | `librekey.txt` | Clé LibreTranslate (optionnelle). |

## Structure de sortie

```
output/<magazine>/
    pdf/
        <NN_slug>.pdf
    articles/<NN_slug>/
        <NN_slug>.md
        <NN_slug>.fr.md        # si traduction
        images/fig_XX.png
```

Les métadonnées des PDF d'articles sont renseignées :
`Title = "<catégorie>: <titre>"`, `Author`, `Subject = "ft:pedia"`.

## Traitement interne

### Découpage

- Articles = entrées de niveau 1 de la table des matières, à partir de
  `--min-page`. Les entrées partageant une page sont regroupées.
- Chaque PDF d'article va de sa page de début à la page précédant l'article
  suivant.

### Ordre de lecture (2 colonnes)

- Les éléments qui traversent toute la largeur (titres, figures pleine largeur)
  servent de séparateurs.
- Dans chaque bande : colonne gauche de haut en bas, puis colonne droite.

### Paragraphes coupés

Un paragraphe est recollé avec le suivant lorsque :

- il ne se termine pas par une ponctuation de fin de phrase, **et**
- la suite commence par une minuscule, **ou** on change de page, **ou** on
  change de colonne, **ou** une illustration (figure/tableau) s'est intercalée.

Cela évite qu'une phrase soit traduite en deux morceaux.

### Figures

- Les tuiles d'image contiguës (même bord X, Y jointif) sont regroupées : une
  figure découpée en bandes est exportée d'un seul tenant.
- Rendu de la zone recollée à `--dpi`.

### Tableaux

- Détectés sur les pages comportant de nombreuses lignes vectorielles.
- Reconstruction par mots + écarts horizontaux (gère les en-têtes fusionnés),
  rendus en tableaux Markdown.
- Légendes `Tab.`/`Tabelle` rattachées.

### Listes

- Puces (`\uf0b7`, `•`, `▪`…) → listes `-`.
- Listes numérotées `1.`/`1)` → listes ordonnées, avec contrainte de séquence
  (1, puis +1) pour éviter les faux positifs (`15)`…).

### Code

- Lignes entièrement en police **Courier** → bloc de code (fenced code block).
- Les commentaires `//` coupés par la largeur de colonne du PDF sont recollés
  sur une seule ligne (une continuation n'a pas de marqueur d'instruction).
- Spans Courier inline dans la prose → code inline (entre accents graves).

### Liens

- Annotations URI → liens Markdown `[texte](url)`.

### Notes de bas de page

- Zone de notes délimitée par un court filet horizontal ; texte en petite
  police ; appel en exposant → `[^n]` et définitions `[^n]: …`.

### Formules mathématiques

- Blocs en police **CambriaMath** (les numéros d'équation `(n)` en police texte
  sont ignorés pour la détection).
- Exposants/indices → `^{…}` / `_{…}`.
- Fractions reconstruites via les barres horizontales.
- Racines reconstruites via le **vinculum** (trait au-dessus du radicande).
- Numéros d'équation conservés en `\tag{n}`.
- Les **mots en clair** contenus dans une formule (souvent des noms de
  grandeurs allemands, p. ex. `Drehwinkel`, `Impulse pro Umdrehung`) sont
  traduits et placés dans `\text{…}` pour un rendu droit dans la langue cible.
  Les indices/exposants (`_{…}`, `^{…}`) et les groupes `\text`/`\mathrm`
  existants sont laissés intacts (identifiants, unités).
- Option `--math-engine pix2tex` : OCR LaTeX sur les zones détectées, avec
  repli sur la reconstruction géométrique si le résultat est douteux.

### Métadonnées d'article

- **Catégorie** : petite ligne non grasse du bloc de titre.
- **Auteur** : bloc court en sans-serif entre le titre et le chapô.
- Écrits en tête du Markdown (`**Kategorie:**`, `**Autor:**`) et dans les
  métadonnées PDF.
- Le titre est apparié de façon robuste entre table des matières et page
  imprimée (césures/espaces ignorés).

### Traduction

- Moteurs : `azure`, `deepl`, `argos` (hors-ligne), `libre`.
- DeepL : plusieurs fichiers de clé possibles ; bascule automatique si une clé
  est épuisée (`456`), invalide (`401`/`403`) ; endpoint `api-free` si la clé
  finit par `:fx`.
- La syntaxe Markdown est protégée : liens, gras/italique, tableaux, code,
  notes et formules ne sont pas altérés.
- Le nom d'auteur n'est jamais traduit.
- Les libellés deviennent spécifiques à la langue (`Auteur :`, `Catégorie :`).
- Quotas : Azure F0 = 2 M car./mois + 2 M car./heure ; DeepL Free =
  500 000 car./mois. Les erreurs de quota sont signalées proprement.

## Limites connues

- Les tableaux « composites » (captures d'écran dans les cellules) ne sont pas
  reconstruits comme tableaux : leurs images restent des figures séparées.
- Un grand tableau coupé par des sauts de page dans le PDF produit plusieurs
  tableaux Markdown successifs.
- La police mathématique du PDF LaTeX n'est pas encore fixée (Computer Modern
  par défaut, non-Microsoft).
- Les notes situées dans des cellules de tableau ne sont pas traitées finement.
- Après modification du script, les `.md` régénérés doivent être retraduits
  pour les articles concernés.
