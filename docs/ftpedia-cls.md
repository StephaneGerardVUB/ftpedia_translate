# `ftpedia.cls` — maquette LaTeX ft:pedia

## Rôle

Classe LaTeX reproduisant la maquette des articles de **ft:pedia** : A4,
deux colonnes, en-tête/pied alternés, polices et styles de titres, légendes,
code et formules.

> Il n'existe pas de template auteur public pour ft:pedia : cette classe est
> une **reconstitution** à partir des PDF publiés.

## Fichiers

```
ftpedia_template/
    ftpedia.cls     # la classe
    example.tex     # article-exemple
    example.pdf     # rendu compilé
```

## Options de classe

| Option | Effet |
|---|---|
| *(aucune)* ou `german` | article en allemand (`Heft n/YYYY`, légendes `Abb.`/`Tab.`) |
| `french` | article en français (`Numéro n/YYYY`, légendes `Fig.`/`Tableau`) |
| `english` | article en anglais |

```latex
\documentclass{ftpedia}
\documentclass[french]{ftpedia}
```

## Document minimal

```latex
\documentclass[french]{ftpedia}

\ftpediaissue{2026}{3}      % en-tête : « Numéro 3/2026 »
\rubrik{Modell}             % catégorie (kicker + en-tête impair)
\titel{Titre de l'article}
\autor{Prénom Nom}

\begin{document}
\artikelkopf                % rubrique + titre + auteur

\begin{ftabstract}
Résumé / chapô en italique, pleine largeur.
\end{ftabstract}

\begin{multicols}{2}
\section{Principe et histoire}
Texte de l'article…

\subsection{1.1 Détails}
Suite du texte…
\end{multicols}

\end{document}
```

Compilation :

```bash
xelatex example.tex && xelatex example.tex
```

## Commandes

| Commande | Rôle |
|---|---|
| `\ftpediaissue{ANNEE}{NUMERO}` | Numéro affiché dans l'en-tête (`NUMERO/ANNEE`). |
| `\rubrik{…}` | Catégorie de l'article (kicker + en-tête des pages impaires). |
| `\titel{…}` | Titre de l'article. |
| `\autor{…}` | Auteur. |
| `\artikelkopf` | Compose rubrique + titre + auteur. |
| `ftabstract` (environnement) | Chapô italique pleine largeur. |
| `\ftpediahref{url}{texte}` | Lien hypertexte bleu souligné. |

## Polices

```latex
\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont{Courier New}
```

Équivalents libres métriquement compatibles (mise en page identique) :

```latex
\setmainfont{Liberation Serif}
\setsansfont{Liberation Sans}
\setmonofont{Liberation Mono}
```

Installation des polices Microsoft sous Fedora (paquet communautaire) :

```bash
sudo dnf install curl cabextract xorg-x11-font-utils fontconfig
sudo rpm --nodigest --nosignature -i \
  https://downloads.sourceforge.net/project/mscorefonts2/rpms/msttcore-fonts-installer-2.6-1.noarch.rpm
fc-cache -fv
```

Vérification : `fc-list | grep -iE "Arial|Times New Roman|Courier New"`.

## Mise en page

- A4, marges gauche/droite 25 mm, haut 30 mm, bas 22 mm.
- Deux colonnes, gouttière 12 mm.
- Corps Times New Roman 12 pt, interligne légèrement augmenté.
- Paragraphes sans alinéa, séparés par un espace vertical.

## Titres

- `\section` : Arial gras 14 pt.
- `\subsection` : Arial gras-italique 12 pt.
- Les numéros (`1.1`, …) sont saisis dans le texte du titre, comme dans la
  revue ; pas de numérotation automatique.

## En-tête

- **Pages impaires** : logo `ft:pedia` à gauche, catégorie (`\rubrik`) à droite.
- **Pages paires** : `Heft n/YYYY` (ou `Numéro n/YYYY` en français) à gauche,
  logo à droite.
- Filet horizontal sous l'en-tête.

Logo : `f` rouge, `t` bleu, `:pedia` gris clair (RGB 165,165,165). L'espacement
inter-caractères XeTeX est désactivé localement pour éviter l'espace avant `:`
en typographie française.

## Pied de page

- Filet horizontal en haut du pied de page.
- Numéro de page : **à gauche si pair**, **à droite si impair**.

## Couleurs

| Nom | Valeur | Usage |
|---|---|---|
| `ftpRed` | RGB 227,30,36 | `f` du logo |
| `ftpBlue` | RGB 0,84,166 | `t` du logo |
| `ftpGrey` | RGB 165,165,165 | `:pedia` du logo |
| `ftpLink` | RGB 0,84,166 | liens hypertextes |

## Liens

Les liens sont bleus et soulignés, avec coupure de ligne possible :

```latex
\ftpediahref{https://exemple.org}{texte du lien}
```

`hyperref` est configuré avec `colorlinks` et la couleur `ftpLink`.

## Légendes

- Figures : Times italique 11 pt, **centrées**.
- Tableaux : Times italique 11 pt, alignées à gauche.
- Libellés : `Abb.`/`Tab.` (allemand), `Fig.`/`Tableau` (français).
- `md2latex.py` utilise `\caption*{…}` pour conserver le texte exact des
  légendes extraites.

## Code

Les blocs utilisent `listings` en Courier New 10 pt, avec coupure des lignes
longues et sans numérotation automatique.

## Mathématiques

`amsmath`/`amssymb` sont chargés. Les formules s'écrivent en `\[ … \]` ou en
environnement `equation`, avec `\tag{n}` pour conserver les numéros d'équation.

La police mathématique reste Computer Modern (police TeX libre) ; aucun choix
de police mathématique Microsoft n'est effectué.

## Dépendances LaTeX

`fontspec`, `polyglossia`, `geometry`, `multicol`, `titlesec`, `fancyhdr`,
`caption`, `listings`, `xcolor`, `graphicx`, `float`, `array`, `tabularx`,
`longtable`, `enumitem`, `microtype`, `amsmath`, `amssymb`, `ulem`,
`hyperref`.

La césure allemande nécessite `hyphen-german` / `texlive-hyphen-german`.
