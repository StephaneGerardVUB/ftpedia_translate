#!/usr/bin/env python3

######################################################################
# This script extracts the content (text and images) from an article #
# of a ftpedia PDF issue and generate a LaTex file from the content. #
######################################################################

# It takes 3 mandatory arguments:
# 1. The path to the PDF file
# 2. The number of the first page to extract
# 3. The number of the last page to extract

import sys
import os
import re
import boto3
import subprocess
import requests, uuid, json
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTTextLineHorizontal, LTChar

##-- Functions

# Displays error message in red and bold characters
def error_message(message):
    print('\033[1;31m' + message + '\033[0m')

# Displays informative message in green and bold characters
def info_message(message):
    print('\033[1;32m' + message + '\033[0m')

# Translates the text content
def aws_translate_german_text(text):
    # send the text to the AWS Translate service
    translate = boto3.client(service_name='translate', region_name='eu-west-1', use_ssl=True)
    result = translate.translate_text(Text=text, SourceLanguageCode="de", TargetLanguageCode="fr")
    return result.get('TranslatedText')

def azure_translate_german_text(endpoint, key, location, to_lang, text):
    # parameters for the Azure translation service
    path = '/translate'
    constructed_url = endpoint + path
    params = {
        'api-version': '3.0',
        'from': 'de',
        'to': to_lang
    }
    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Ocp-Apim-Subscription-Region': location,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }
    body = [{
        'text': text
    }]
    response = requests.post(constructed_url, params=params, headers=headers, json=body)
    return response.json()[0]['translations'][0]['text']

# Sanitize the spaces in a string
def sanitize_spaces(s):
    # replace sequences of 4 spaces or more by 3 spaces
    # until there are no more sequences of 4 spaces or more
    while s.find('    ') != -1:
        s = s.replace('    ', '   ')
    # replace all sequences of 3 spaces by a single space except the last sequence
    while s.count('   ') > 1:
        s = s.replace('   ', ' ', s.count('   ') - 1)
    return s

# Puts the first letter of a string in uppercase
def capitalize(s):
    return s[0].upper() + s[1:]

# Detects if the the text of a line is aligned to the right
def is_right_aligned(line):
    # if the line contains only spaces, then it is not considered as right aligned
    if line.strip() == '':
        print("Line is empty or contains only spaces, not right aligned.")
        return False
    # if the line starts with at least 20 spaces, then it is right aligned
    if re.match(r'^\s{20,}', line):
        # print the line to debug
        print("Line is right aligned: '%s'" % line.strip())
        return True
    # otherwise, it is not right aligned
    return False

# Get the abstract of the article
def get_abstract_from_pdf(pdf_file):
    abstract = ''
    # get first page
    page1 = next(extract_pages(pdf_file))
    element_index = 0
    for element in page1:
        if isinstance(element, LTTextContainer):
            container_size = element.width
            if element_index >= 3 and container_size >= 400:
                for text_line in element:
                    if isinstance(text_line, LTTextLineHorizontal):
                        abstract += text_line.get_text().strip() + ' '
        element_index += 1
    return abstract.strip()

# Get the title of the article
def get_title_from_pdf(pdf_file):
    title = ''
    # get first page
    page1 = next(extract_pages(pdf_file))
    element_index = 0
    for element in page1:
        if isinstance(element, LTTextContainer):
            for text_line in element:
                # the first lines found with font size 20 are the title
                if isinstance(text_line, LTTextLineHorizontal):
                    character = next(iter(text_line), None)
                    if isinstance(character, LTChar):
                        character.size = round(character.size)
                        font_size = character.size
                        if font_size == 20 and element_index > 1:
                            title += text_line.get_text().strip() + ' '
                            break
        if title:
            break
        element_index += 1
    return title.strip()

##-- Process arguments

# check if the number of arguments is correct
if len(sys.argv) != 6:
    error_message('Usage: ftpedia_pdf_article_to_latex.py <pdf_file> -f <first_page> -l <last_page>')
    sys.exit(1)

# prcocess the arguments
pdf_file = sys.argv[1]

# the first page number is introduced by '-f' or '--first'
if sys.argv[2] in ['-f', '--first']:
    first_page = int(sys.argv[3])
# the last page number is introduced by '-l' or '--last'
if sys.argv[4] in ['-l', '--last']:
    last_page = int(sys.argv[5])

# compute the number of pages to extract
nbpages = last_page - first_page + 1
fpagenum = first_page
lpagenum = last_page

# check if the PDF filename has the good format for an ftpedia issue
if not re.match(r'ftpedia-[0-9]{4}-[0-9].pdf', pdf_file):
    error_message('The PDF file is not a ftpedia issue.')
    sys.exit(1)

# check if the PDF file exists
if not os.path.exists(pdf_file):
    print('The PDF file does not exist.')
    # ask the user if he wants to download the file
    download = input('Do you want to download the file? [y/n] ')
    if download == 'y':
        # get the year from the file name
        year = re.search(r'ftpedia-([0-9]{4})-[0-9].pdf', pdf_file).group(1)
        # get the issue number from the file name
        issue = re.search(r'ftpedia-[0-9]{4}-([0-9]).pdf', pdf_file).group(1)
        # generate the url of the file
        urlftpedia = 'https://www.ftcommunity.de/ftpedia/{0}/{0}-{1}/ftpedia-{0}-{1}.pdf'.format(year, issue)
        # download the file
        os.system('wget {}'.format(urlftpedia))
        # check if the download was successful
        if os.path.exists(pdf_file):
            print('The file has been downloaded successfully.')
        else:
            error_message('An error occurred while downloading the file.')
            sys.exit(1)
    else:
        error_message('The PDF file does not exist.')
        sys.exit(1)

# check that first_page and last_page are valid
if first_page < 1:
    error_message('The first page number must be greater than 0.')
    sys.exit(1)
if last_page < first_page:
    error_message('The last page number must be greater than or equal to the first page number.')
    sys.exit(1)


##-- Check that the tools are installed

# check if pdftk is installed
if os.system('pdftk --version >/dev/null') != 0:
    error_message('pdftk is not installed. Please install it before running this script.')
    sys.exit(1)

# check if pdftotext is installed
if os.system('pdftotext -v >/dev/null') != 0:
    error_message('pdftotext is not installed. Please install it before running this script.')
    sys.exit(1) 

# check if pdfimages is installed
if os.system('pdfimages -v >/dev/null') != 0:
    error_message('pdfimages is not installed. Please install it before running this script.')
    sys.exit(1)


##-- Extract the text content

# Tell the user that the script is extracting the text content
info_message('Extracting the text content...')

# Using command pdftk to extract the specified pages
os.system('pdftk {} cat {}-{} output temp.pdf'.format(pdf_file, first_page, last_page))
#os.system('pdftotext temp.pdf')

#-----------------------------------------------------------------------------------------#
# use the command pdftotext on temp.pdf to convert pdf to text preserving layout
os.system('pdftotext -q -layout temp.pdf temp1.txt')

# extract category,title and author of the article
category = ''
title = ''
author = ''
abstract = ''
cptr = 0
with open('temp1.txt', 'r') as f:
    line = f.readline()
    line = f.readline()
    cptr = 2
    while not line.strip():
        line = f.readline()
        cptr += 1
    category = line.strip()
    category = capitalize(category)
    while line.strip():
        line = f.readline()
        cptr += 1
        if not is_right_aligned(line):
            title = title + line.strip() + ' '
        else:
            author = line.strip()
            line = f.readline()
            cptr += 1
            break
    while not line.strip():
        line = f.readline()
        cptr += 1
    if author == '' and is_right_aligned(line):
        author = line.strip()
        line = f.readline()
        cptr += 1
    while line.strip():
        line = f.readline()
        cptr += 1
print('CATEGORY: ' + category)
title = get_title_from_pdf('temp.pdf')
print('TITLE: ' + title)
print('AUTHOR: ' + author)
abstract = get_abstract_from_pdf('temp.pdf')
print('ABSTRACT: ' + abstract)
startbody = cptr

# find the line numbers of the lines with a page number
pagenumbers = []
with open('temp1.txt', 'r') as f:
    for i, line in enumerate(f):
        if line.strip().isdigit() and int(line.strip()) >= fpagenum and int(line.strip()) <= lpagenum:
            pagenumbers.append(i + 1)
print(pagenumbers)

# put all the text of the article in a list of strings
bodytext = []
with open('temp1.txt', 'r') as f:
    for i, line in enumerate(f):
        if i >= startbody:
            bodytext.append(line)

# bodytextpages is a list of strings, each string is the text of a page
bodytextpages = []
cptr = 0
for i in range(nbpages):
    bodytextpages.append('')
    for line in bodytext[cptr:]:
        cptr += 1
        if line.strip().isdigit():
            break
        # let's ignore headers
        if line.strip().startswith('ft:pedia') and line.strip().endswith(category):
            continue
        if line.strip().startswith('Heft') and line.strip().endswith('ft:pedia'):
            continue
        bodytextpages[i] += line

# loop over the pages and extract the text by columns
newbody = ''
cptr = 0
for page in bodytextpages:
    cptr += 1
    leftcolumn = ''
    rightcolumn = ''
    # read the page line by line
    for line in page.splitlines():
        # if line begins with at least 45 spaces, it's a right line
        if re.match(r'^\s{45,}', line):
            rightline = line.strip()
            leftline = ''
        elif line.strip().find('   ') == -1:
            leftline = line.strip()
            rightline = ''
        else:
            if line.strip().count('   ') > 1:
                (leftline,rightline) = sanitize_spaces(line).lstrip().split('   ', 1)
            else:
                (leftline,rightline) = line.lstrip().split('   ', 1)
        leftcolumn += leftline + '\n'
        rightcolumn += rightline.strip() + '\n'
    newbody += leftcolumn
    newbody += rightcolumn

# print newbody to temp2.txt
with open('temp2.txt', 'w') as f:
    f.write(newbody)

#-----------------------------------------------------------------------------------------#

# Cleaning the text file (specific to ftpedia PDFs)
cleanedlines = []
curlineblank = False
prevlineblank = False
with open('temp2.txt', 'r') as filesrc:
    lines = filesrc.readlines()
    for line in lines:
        # if the current line is blanck, then set the variable curlineblank to True
        if not line.strip():
            curlineblank = True
        else:
            curlineblank = False
        # ignore two consecutive blank lines
        if curlineblank and prevlineblank:
            prevlineblank = True
            continue
        prevlineblank = curlineblank
        # if none of the previous conditions are met, then add the line to the list of cleaned lines
        cleanedlines.append(line)

# write the cleaned lines to the file temp2.txt
with open('temp3.txt', 'w') as filedst:
    filedst.writelines(cleanedlines)

# Ask the user if he wants to edit the file temp4.txt to fix some issues in the text
openfile = input('Do you want to open the text to fix some issues? [y/n]')
if openfile == 'y':
    return_code = subprocess.call(['xed', 'temp3.txt'])

# Reassemble the sentences in the paragraphs
with open('temp3.txt', 'r') as filesrc:
    paragraph = ''
    lines = filesrc.readlines()
    for line in lines:
        # strip the newline character
        line = line.strip()
        # if the line is empty, add an empty line to the file temp4.txt
        if not line:
            with open('temp4.txt', 'a') as filedst:
                filedst.write(paragraph.strip() + '\n\n')
                paragraph = ''
            next
        else:
            # if the line is not empty, add the line to the paragraph
            # if the last character of the line is a dash, remove the dash
            if line[-1] == '-':
                paragraph += line[:-1]
            else:
                paragraph += line + ' '
            next

##-- Extract the images

# Tell the user that the script is extracting the images
info_message('Extracting the images...')

# Create a directory to store the images
if not os.path.exists('images'):
    os.makedirs('images')

# Using command pdfimages to extract the images from the PDF file
os.system('pdfimages -q -png -f {0} -l {1} {2} images/'.format(first_page, last_page, pdf_file))

# Rename the images
files = os.listdir('images')
for file in files:
    # if the file is a PNG file, then
    if file.endswith('.png'):
        # get the number of the image
        num = re.search(r'([0-9]+)', file).group(1).lstrip('0')
        if num == '':
            num = '0'
        # increment the number of the image
        num = str(int(num) + 1)
        # rename the file
        os.rename('images/' + file, 'images/abb' + num + '.png')


##-- Translate the text content
sys.exit(0)
# tell the user that the script is translating the text content
info_message('Translating the text content...')

# check the presence of the Azure key file
if not os.path.exists('azurekey.txt'):
    error_message('The Azure key file azurekey.txt does not exist.')
    error_message('Please create the file and put the Azure key in it.')
    sys.exit(1)

# parameters for the Azure translation service
with open('azurekey.txt', 'r') as file:
    key = file.read().strip()
endpoint = 'https://api.cognitive.microsofttranslator.com/'
location = 'westeurope'
to_lang = 'fr'

# send the lines to the AWS Translate service
filepath = 'temp4.txt'
translatedtext = ''
with open(filepath) as fp:
    line = fp.readline()
    cnt = 1
    while line :
        linestripped = line
        linestripped.strip()
        result = azure_translate_german_text(endpoint, key, location, to_lang, linestripped)
        translatedtext += result
        line = fp.readline()
        cnt += 1

# Write the translated text to a file
with open('temp5.txt', 'w') as f:
    f.write(translatedtext)

##-- Generate the LaTex file

# Tell the user that the script is generating the LaTex file
info_message('Generating the LaTex file...')

# Check that template.tex exists
if not os.path.exists('template.tex'):
    error_message('The template file template.tex does not exist.')
    sys.exit(1)

# the list of tags that are in template.tex
tags = ['<@numero@>', '<@auteur@>', '<@categorie@>', '<@titre@>', '<@firstpagenumber@>', '<@abstract@>']

# list of strings to replace the tags
infos = ['123456', 'John Doe', 'Optique', 'Détecteur d\'ondes gravitationnelles', '666', 'Lorem ipsum dolor']

# author's name to the user
infos[0] = pdf_file.split('-')[2].split('.')[0] + '/' + pdf_file.split('-')[1]
infos[1] = author
infos[2] = category
infos[3] = title
infos[4] = str(first_page)

# translate the category and the title and the abstract
infos[2] = capitalize(azure_translate_german_text(endpoint, key, location, to_lang, infos[2]))
infos[3] = azure_translate_german_text(endpoint, key, location, to_lang, infos[3])
infos[5] = azure_translate_german_text(endpoint, key, location, to_lang, abstract)

# # let's check the collected informations
# for i, tag in enumerate(tags):
#     print(tag, tags[i], infos[i])

# template.tex is the template file
tplfilename = 'template.tex'

# get filename without extension of the pdf file
texfilename = pdf_file.split('.')[0] + '_FR.tex'

# create a copy of file 'template.tex', the name of the copy is 'filename.tex'
os.system('cp template.tex ' + texfilename)

# open the file 'filename.tex' in write mode
lines = []
with open(tplfilename, 'r') as file:
    # read all lines of the file
    lines = file.readlines()
    # iterate over the list of tags
    for i, tag in enumerate(tags):
        # replace the string 'tag' by the string 'tag' + str(i)
        lines = [line.replace(tag, infos[i]) for line in lines]

# create the file texfilename with the modified lines
with open(texfilename, 'w') as file:
    file.writelines(lines)

# read the content of the file 'temp5.txt' and replace the tag '<@content@>' in texfilename with this content
with open('temp5.txt', 'r') as file:
    content = file.read()
    with open(texfilename, 'r') as file:
        lines = file.readlines()
        for i, line in enumerate(lines):
            # if the line contains the tag '<@content@>', then
            if '<@content@>' in line:
                # replace the tag '<@content@>' by the content of the file 'temp5.txt'
                lines[i] = line.replace('<@content@>', content)
    with open(texfilename, 'w') as file:
        file.writelines(lines)

# define a heredoc string that is a tex template for a figure
tplfig = '''
\\begin{minipage}[h]{7.5cm}
	\\centering
    \\includegraphics[width=7.5cm]{images/abb<@numfig@>.png}
    \\captionof{figure}{<@caption@>}
    \\vspace{0.6cm}
\\end{minipage}
'''

# in texfilename, replace the lines beginning with 'Figure' by the template tplfig
with open(texfilename, 'r') as file:
    lines = file.readlines()
    for i, line in enumerate(lines):
        # check if line is starting with 'Figure' or 'Fig.' followed by a number using regular expression
        if re.match(r'^(Figure|Fig.)\s[0-9]+\s*:', line):
            lines[i] = tplfig.replace('<@numfig@>', line.split(' ')[1].rstrip(':').rstrip())
            lines[i] = lines[i].replace('<@caption@>', line.split(':')[1].strip())

    with open(texfilename, 'w') as file:
        file.writelines(lines)
