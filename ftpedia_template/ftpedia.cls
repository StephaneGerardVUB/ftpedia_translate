% ftpedia.cls -- article layout for the fischertechnik magazine "ft:pedia"
% Compile with XeLaTeX or LuaLaTeX (fontspec).
% Fonts: Liberation Serif/Sans/Mono are metric-compatible with the
% Times New Roman / Arial / Courier used in the published magazine.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{ftpedia}[2026/10/21 ft:pedia article class]

\LoadClass[12pt,a4paper,twoside]{article}

% Main language of the document: german (default), french or english.
\DeclareOption{german}{\def\ftpedia@lang{german}}
\DeclareOption{french}{\def\ftpedia@lang{french}}
\DeclareOption{english}{\def\ftpedia@lang{english}}
\ExecuteOptions{german}
\ProcessOptions\relax

% Language-dependent words used in the running header.
\def\ftpedia@french{french}
\ifx\ftpedia@lang\ftpedia@french
  \def\ftpedia@issueword{Numéro}
\else
  \def\ftpedia@issueword{Heft}
\fi

\RequirePackage{fontspec}
\RequirePackage{polyglossia}
\setmainlanguage{\ftpedia@lang}
\renewcommand{\figurename}{Abb.}
\renewcommand{\tablename}{Tab.}
\RequirePackage{geometry}
\RequirePackage{multicol}
\RequirePackage{titlesec}
\RequirePackage{fancyhdr}
\RequirePackage{caption}
\RequirePackage{listings}
\RequirePackage{xcolor}
\RequirePackage{graphicx}
\RequirePackage{float}
\RequirePackage{array}
\RequirePackage{tabularx}
\RequirePackage{longtable}
\RequirePackage{enumitem}
\RequirePackage{microtype}
\RequirePackage{amsmath,amssymb}
\RequirePackage[normalem]{ulem}
\RequirePackage[hidelinks]{hyperref}

% ---------------------------------------------------------------------------
% Fonts (Microsoft core fonts, matching the published magazine)
% Free alternative (metric-compatible): Liberation Serif/Sans/Mono.
% ---------------------------------------------------------------------------
\setmainfont{Times New Roman}
\setsansfont{Arial}
\setmonofont{Courier New}

% ---------------------------------------------------------------------------
% Page geometry (A4, two columns, ft:pedia margins)
% ---------------------------------------------------------------------------
\geometry{a4paper,left=25mm,right=25mm,top=30mm,bottom=22mm,
          headheight=22pt,headsep=6mm,footskip=12mm,columnsep=12mm}

\definecolor{ftpRed}{RGB}{227,30,36}
\definecolor{ftpBlue}{RGB}{0,84,166}
\definecolor{ftpGrey}{RGB}{165,165,165}
\definecolor{ftpLink}{RGB}{0,84,166}

\hypersetup{colorlinks=true,urlcolor=ftpLink,linkcolor=ftpLink}

% Blue, underlined hyperlinks (breaks across lines thanks to ulem).
\newcommand{\ftpediahref}[2]{\href{#1}{\textcolor{ftpLink}{\uline{#2}}}}

\setlength{\parindent}{0pt}
\setlength{\parskip}{2.2mm}
\setlength{\emergencystretch}{3em}
\linespread{1.04}

% ---------------------------------------------------------------------------
% Headings: Section = Arial bold 14 pt, Subsection = Arial bold-italic 12 pt.
% Numbers are typed directly in the heading text, as in the magazine
% (e.g. \subsection{1.1 IO}); sections are therefore not auto-numbered.
% ---------------------------------------------------------------------------
\setcounter{secnumdepth}{0}
\titleformat{\section}{\sffamily\bfseries\fontsize{14}{17}\selectfont}{}{0pt}{}
\titleformat{\subsection}{\sffamily\bfseries\itshape\fontsize{12}{14.4}\selectfont}{}{0pt}{}
\titlespacing*{\section}{0pt}{5mm}{2mm}
\titlespacing*{\subsection}{0pt}{4mm}{1.5mm}

% ---------------------------------------------------------------------------
% Captions: Times italic 11 pt, "Abb. 1: ..."
% ---------------------------------------------------------------------------
\captionsetup{font={small,it},labelfont=it,labelsep=colon,
              justification=raggedright,singlelinecheck=false,skip=2mm}
\captionsetup[figure]{name=Abb.,justification=centering}
\captionsetup[table]{name=Tab.}

% ---------------------------------------------------------------------------
% Code listings: Courier/Mono 10 pt
% ---------------------------------------------------------------------------
\lstset{basicstyle=\ttfamily\fontsize{10}{12}\selectfont,
        columns=fullflexible,keepspaces=true,showstringspaces=false,
        breaklines=true,frame=none,numbers=none,
        xleftmargin=0pt,aboveskip=2mm,belowskip=2mm}

\setlist[itemize]{leftmargin=1.2em,itemsep=0.4mm,topsep=1mm,parsep=0pt}
\setlist[enumerate]{leftmargin=1.6em,itemsep=0.4mm,topsep=1mm,parsep=0pt}

% ---------------------------------------------------------------------------
% Running header and footer
% ---------------------------------------------------------------------------
\gdef\ftpedia@issue{1/2025}
\gdef\ftpedia@rubrik{}
\gdef\ftpedia@titel{}
\gdef\ftpedia@autor{}

\newcommand{\ftpediaissue}[2]{\gdef\ftpedia@issue{#2/#1}}
\newcommand{\rubrik}[1]{\gdef\ftpedia@rubrik{#1}}
\newcommand{\titel}[1]{\gdef\ftpedia@titel{#1}}
\newcommand{\autor}[1]{\gdef\ftpedia@autor{#1}}

\newcommand{\ftpedia@logo}{{%
  \ifdefined\XeTeXinterchartokenstate\XeTeXinterchartokenstate=0\relax\fi
  \sffamily\bfseries\fontsize{22}{24}\selectfont
  \textcolor{ftpRed}{f}\textcolor{ftpBlue}{t}\textcolor{ftpGrey}{:pedia}}}
\newcommand{\ftpedia@header}{{\sffamily\fontsize{12}{14}\selectfont \ftpedia@issueword\ \ftpedia@issue}}
\newcommand{\ftpedia@category}{{\sffamily\fontsize{12}{14}\selectfont \ftpedia@rubrik}}

% Odd pages: logo on the left, category on the right.
% Even pages: "Heft n/YYYY" on the left, logo on the right.
\pagestyle{fancy}
\fancyhf{}
\fancyhead[LO]{\ftpedia@logo}
\fancyhead[RO]{\ftpedia@category}
\fancyhead[LE]{\ftpedia@header}
\fancyhead[RE]{\ftpedia@logo}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0.4pt}
\fancyfoot[LE]{\sffamily\fontsize{10}{12}\selectfont\thepage}
\fancyfoot[RO]{\sffamily\fontsize{10}{12}\selectfont\thepage}

% ---------------------------------------------------------------------------
% Article head: kicker (rubric), title and author
% ---------------------------------------------------------------------------
\newcommand{\artikelkopf}{%
  \begingroup
  \noindent
  {\sffamily\fontsize{12}{14.4}\selectfont\ftpedia@rubrik\par}%
  \vspace{1mm}%
  {\sffamily\bfseries\fontsize{20}{23}\selectfont\ftpedia@titel\par}%
  \vspace{2mm}%
  {\sffamily\fontsize{12}{14.4}\selectfont\hfill\ftpedia@autor\par}%
  \vspace{3mm}%
  \endgroup
}

% ---------------------------------------------------------------------------
% Abstract / standfirst (italic, full width, before the two columns)
% ---------------------------------------------------------------------------
\newenvironment{ftabstract}
  {\par\noindent\itshape\fontsize{12}{14.4}\selectfont\ignorespaces}
  {\par\vspace{4mm}}

% Short caption labels, matching the language of the article.
\AtBeginDocument{%
  \ifx\ftpedia@lang\ftpedia@french
    \renewcommand{\figurename}{Fig.}%
    \renewcommand{\tablename}{Tableau}%
  \else
    \renewcommand{\figurename}{Abb.}%
    \renewcommand{\tablename}{Tab.}%
  \fi
}

\endinput
