#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import re
from typing import cast

import requests

TRANSLATIONS_DIR = pathlib.Path(__file__).resolve().parent
TRANSLATIONS_LANGUAGES = TRANSLATIONS_DIR / "languages.json"

OPENAI_MODEL = "deepseek-chat"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_PROMPT = "You are a professional translator from English to {language} (ISO 639 language code). " + \
                "The following sentence or word is in the GUI of a software called openpilot, translate it accordingly."


def get_language_files(languages: list[str] = None) -> dict[str, pathlib.Path]:
  files = {}

  with open(TRANSLATIONS_LANGUAGES) as fp:
    language_dict = json.load(fp)

    for filename in language_dict.values():
      path = TRANSLATIONS_DIR / f"app_{filename}.po"
      language = filename

      if languages is None or language in languages:
        files[language] = path

  return files


def translate_phrase(text: str, language: str) -> str:
  response = requests.post(
    "https://api.deepseek.com/chat/completions",
    json={
      "model": OPENAI_MODEL,
      "messages": [
        {
          "role": "system",
          "content": OPENAI_PROMPT.format(language=language),
        },
        {
          "role": "user",
          "content": text,
        },
      ],
      "temperature": 0.8,
      "max_tokens": 1024,
      "top_p": 1,
    },
    headers={
      "Authorization": f"Bearer {OPENAI_API_KEY}",
      "Content-Type": "application/json",
    },
  )

  if 400 <= response.status_code < 600:
    raise requests.HTTPError(f'Error {response.status_code}: {response.json()}', response=response)

  data = response.json()

  return cast(str, data["choices"][0]["message"]["content"])


def translate_file(path: pathlib.Path, language: str, all_: bool) -> None:
  # Read the PO file
  with path.open("r", encoding="utf-8") as fp:
    lines = fp.readlines()

  # Process each line to find translation entries
  i = 0
  while i < len(lines):
    line = lines[i].strip()

    # Look for msgid line
    if line.startswith('msgid'):
      # Check for empty msgid (header) - this is the start of multi-line msgid
      if line == 'msgid ""':
        # This is a multi-line msgid entry
        msgid_text = ""
        j = i + 1  # Start from the next line
        
        # Collect all the quoted lines that form the msgid
        while j < len(lines) and lines[j].strip().startswith('"'):
          msgid_text += lines[j].strip().strip('"')
          j += 1

        # Skip header entry (empty msgid)
        if not msgid_text:
          i = j
          continue

        # Look for the corresponding msgstr or msgid_plural
        k = j
        has_plural = False
        while k < len(lines) and not lines[k].strip().startswith('msgstr'):
          if lines[k].strip().startswith('msgid_plural'):
            has_plural = True
          k += 1

        if k < len(lines):
          # Handle plural forms
          if has_plural:
            # This is a plural entry, need to handle msgstr[0], msgstr[1], etc.
            msgstr_texts = []
            m = k
            
            # Find all msgstr[n] entries
            while m < len(lines) and lines[m].strip().startswith('msgstr['):
              msgstr_match = re.match(r'msgstr\[(\d+)\]\s*"(.*)"', lines[m].strip())
              if msgstr_match:
                msgstr_texts.append(msgstr_match.group(2))
              m += 1
            
            # Check if we should translate this entry
            should_translate = False
            if all_:
              should_translate = True
            else:
              # Only translate if all msgstr entries are empty or contain only whitespace
              should_translate = all(not text.strip() for text in msgstr_texts)
            
            if should_translate:
              # Translate both singular and plural forms
              singular_text = msgid_text
              # Find the plural form
              plural_text = ""
              p = j
              while p < k and not lines[p].strip().startswith('msgid_plural'):
                p += 1
              if p < k:
                # Extract plural text
                plural_match = re.match(r'msgid_plural\s*"(.*)"', lines[p].strip())
                if plural_match:
                  plural_text = plural_match.group(1)
              
              # Translate both forms
              singular_translation = translate_phrase(singular_text, language)
              plural_translation = translate_phrase(plural_text, language)
              
              print(f"Translating plural entry:")
              print(f"Singular: {singular_text}")
              print(f"Plural: {plural_text}")
              print(f"Singular translation: {singular_translation}")
              print(f"Plural translation: {plural_translation}")
              print("-" * 50)
              
              # Update msgstr[0] and msgstr[1]
              m = k
              idx = 0
              while m < len(lines) and lines[m].strip().startswith('msgstr['):
                if idx == 0:
                  lines[m] = f'msgstr[0] "{singular_translation}"\n'
                elif idx == 1:
                  lines[m] = f'msgstr[1] "{plural_translation}"\n'
                idx += 1
                m += 1
              
              i = m
              continue
            else:
              i = k + len(msgstr_texts)
              continue
          else:
            # Extract msgstr text (handle multi-line msgstr)
            msgstr_text = ""
            m = k
            
            # Check if this is a multi-line msgstr
            if lines[m].strip() == 'msgstr ""':
              # Multi-line msgstr - collect all quoted lines
              m += 1
              while m < len(lines) and lines[m].strip().startswith('"'):
                msgstr_text += lines[m].strip().strip('"')
                m += 1
            else:
              # Single-line msgstr
              msgstr_match = re.match(r'msgstr\s+"(.+)"', lines[m].strip())
              if msgstr_match:
                msgstr_text = msgstr_match.group(1)

            # Check if we should translate this entry
            should_translate = False
            if all_:
              should_translate = True
            else:
              # Only translate if msgstr is empty or contains only whitespace
              if not msgstr_text.strip():
                should_translate = True

          if should_translate:
            # Translate the phrase
            llm_translation = translate_phrase(msgid_text, language)

            print(f"Translating entry:")
            print(f"Source: {msgid_text}")
            print(f"LLM translation: {llm_translation}")
            print("-" * 50)

            # Update the msgstr line
            if lines[k].strip() == 'msgstr ""':
              # Multi-line msgstr - replace with multi-line format
              # Remove existing msgstr lines
              m = k + 1
              while m < len(lines) and lines[m].strip().startswith('"'):
                lines[m] = ""
                m += 1
              
              # Add new multi-line msgstr
              lines[k] = 'msgstr ""\n'
              # Split translation into lines of reasonable length
              translation_lines = []
              current_line = ""
              for word in llm_translation.split():
                if len(current_line + word) > 60:  # Reasonable line length
                  translation_lines.append(f'"{current_line}"\n')
                  current_line = word
                else:
                  if current_line:
                    current_line += " " + word
                  else:
                    current_line = word
              if current_line:
                translation_lines.append(f'"{current_line}"\n')
              
              # Insert the translation lines
              for idx, trans_line in enumerate(translation_lines):
                lines.insert(k + 1 + idx, trans_line)
            else:
              # Single-line msgstr - replace it
              lines[k] = f'msgstr "{llm_translation}"\n'

            i = k + 1
            continue
          else:
            i = k + 1
            continue
        
        i = j
        continue
      
      # Single-line msgid
      msgid_match = re.match(r'msgid\s+"(.+)"', line)
      if msgid_match:
        msgid_text = msgid_match.group(1)

        # Skip header entry (empty msgid)
        if not msgid_text:
          i += 1
          continue

        # Look for the corresponding msgstr or msgid_plural
        j = i + 1
        has_plural = False
        while j < len(lines) and not lines[j].strip().startswith('msgstr'):
          if lines[j].strip().startswith('msgid_plural'):
            has_plural = True
          j += 1

        if j < len(lines):
          # Handle plural forms
          if has_plural:
            # This is a plural entry, need to handle msgstr[0], msgstr[1], etc.
            msgstr_texts = []
            m = j
            
            # Find all msgstr[n] entries
            while m < len(lines) and lines[m].strip().startswith('msgstr['):
              msgstr_match = re.match(r'msgstr\[(\d+)\]\s*"(.*)"', lines[m].strip())
              if msgstr_match:
                msgstr_texts.append(msgstr_match.group(2))
              m += 1
            
            # Check if we should translate this entry
            should_translate = False
            if all_:
              should_translate = True
            else:
              # Only translate if all msgstr entries are empty or contain only whitespace
              should_translate = all(not text.strip() for text in msgstr_texts)
            
            if should_translate:
              # Translate both singular and plural forms
              singular_text = msgid_text
              # Find plural form
              plural_text = ""
              p = i + 1
              while p < j and not lines[p].strip().startswith('msgid_plural'):
                p += 1
              if p < j:
                # Extract plural text
                plural_match = re.match(r'msgid_plural\s*"(.*)"', lines[p].strip())
                if plural_match:
                  plural_text = plural_match.group(1)
              
              # Translate both forms
              singular_translation = translate_phrase(singular_text, language)
              plural_translation = translate_phrase(plural_text, language)
              
              print(f"Translating plural entry:")
              print(f"Singular: {singular_text}")
              print(f"Plural: {plural_text}")
              print(f"Singular translation: {singular_translation}")
              print(f"Plural translation: {plural_translation}")
              print("-" * 50)
              
              # Update msgstr[0] and msgstr[1]
              m = j
              idx = 0
              while m < len(lines) and lines[m].strip().startswith('msgstr['):
                if idx == 0:
                  lines[m] = f'msgstr[0] "{singular_translation}"\n'
                elif idx == 1:
                  lines[m] = f'msgstr[1] "{plural_translation}"\n'
                idx += 1
                m += 1
              
              i = m
              continue
            else:
              i = j + len(msgstr_texts)
              continue
          else:
            # Extract msgstr text (handle multi-line msgstr)
            msgstr_text = ""
            m = j
            
            # Check if this is a multi-line msgstr
            if lines[m].strip() == 'msgstr ""':
              # Multi-line msgstr - collect all quoted lines
              m += 1
              while m < len(lines) and lines[m].strip().startswith('"'):
                msgstr_text += lines[m].strip().strip('"')
                m += 1
            else:
              # Single-line msgstr
              msgstr_match = re.match(r'msgstr\s+"(.+)"', lines[m].strip())
              if msgstr_match:
                msgstr_text = msgstr_match.group(1)

            # Check if we should translate this entry
            should_translate = False
            if all_:
              should_translate = True
            else:
              # Only translate if msgstr is empty or contains only whitespace
              if not msgstr_text.strip():
                should_translate = True

          if should_translate:
            # Translate the phrase
            llm_translation = translate_phrase(msgid_text, language)

            print(f"Translating entry:")
            print(f"Source: {msgid_text}")
            print(f"LLM translation: {llm_translation}")
            print("-" * 50)

            # Update the msgstr line
            if lines[j].strip() == 'msgstr ""':
              # Multi-line msgstr - replace with multi-line format
              # Remove existing msgstr lines
              m = j + 1
              while m < len(lines) and lines[m].strip().startswith('"'):
                lines[m] = ""
                m += 1
              
              # Add new multi-line msgstr
              lines[j] = 'msgstr ""\n'
              # Split translation into lines of reasonable length
              translation_lines = []
              current_line = ""
              for word in llm_translation.split():
                if len(current_line + word) > 60:  # Reasonable line length
                  translation_lines.append(f'"{current_line}"\n')
                  current_line = word
                else:
                  if current_line:
                    current_line += " " + word
                  else:
                    current_line = word
              if current_line:
                translation_lines.append(f'"{current_line}"\n')
              
              # Insert the translation lines
              for idx, trans_line in enumerate(translation_lines):
                lines.insert(j + 1 + idx, trans_line)
            else:
              # Single-line msgstr - replace it with single-line format
              lines[j] = f'msgstr "{llm_translation}"\n'

            i = j + 1
            continue
          else:
            i = j + 1
            continue

    i += 1

  # Write the updated PO file back with original formatting preserved
  with path.open("w", encoding="utf-8") as fp:
    fp.writelines(lines)


def main():
  arg_parser = argparse.ArgumentParser("Auto translate")

  group = arg_parser.add_mutually_exclusive_group(required=True)
  group.add_argument("-a", "--all-files", action="store_true", help="Translate all files")
  group.add_argument("-f", "--file", nargs="+", help="Translate the selected files. (Example: -f fr de)")

  arg_parser.add_argument("-t", "--all-translations", action="store_true", default=False, help="Translate all sections. (Default: only unfinished)")

  args = arg_parser.parse_args()

  if OPENAI_API_KEY is None:
    print("OpenAI API key is missing. (Hint: use `export OPENAI_API_KEY=YOUR-KEY` before you run the script).\n" +
          "If you don't have one go to: https://beta.openai.com/account/api-keys.")
    exit(1)

  files = get_language_files(None if args.all_files else args.file)

  if args.file:
    missing_files = set(args.file) - set(files)
    if len(missing_files):
      print(f"No language files found: {missing_files}")
      exit(1)

  print(f"Translation mode: {'all' if args.all_translations else 'only unfinished'}. Files: {list(files)}")

  for lang, path in files.items():
    print(f"Translate {lang} ({path})")
    translate_file(path, lang, args.all_translations)


if __name__ == "__main__":
  main()
