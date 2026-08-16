#!/usr/bin/env python3
"""
Export generated ABAP code into the abapGit-formatted repo so it can be
pulled into SAP via zabapgit.

Handles the object types CLAUDE.md's conventions actually generate:
  - Executable reports (REPORT ...)              -> <name>.prog.abap + .prog.xml
  - Global classes (CLASS ... DEFINITION PUBLIC)  -> <name>.clas.abap + .clas.xml
  - Tables (.tabl files, see CLAUDE.md format)    -> <name>.tabl.xml
  - Structures (.struc files, same format)        -> <name>.struc.xml

Dictionary object (.tabl/.struc) conversion is best-effort, particularly
for fields using an inline built-in type rather than referencing an
existing data element -- test-pull and activate a trial object in SAP
before trusting this for real work.

Other object types (function groups, CDS, etc.) are not converted -- they're
listed as skipped so you know to handle them manually.

Usage:
    python3 export_to_abapgit.py <ticket-key> [--push]

Reads the LATEST iteration's files from generated/<ticket-key>/, writes
converted files into ../sap-abapgit-repo/src/, and (with --push) commits
and pushes them.
"""

import os
import re
import subprocess
import sys

from dotenv import load_dotenv

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_DIR = os.path.join(PROJECT_DIR, "generated")

load_dotenv(os.path.join(PROJECT_DIR, ".env"))
ABAPGIT_REPO_DIR = os.environ.get("ABAPGIT_REPO_DIR", "")
if not ABAPGIT_REPO_DIR:
    raise SystemExit(
        "ABAPGIT_REPO_DIR is not set. Run `python3 setup.py` first, or set it in .env."
    )
ABAPGIT_SRC_DIR = os.path.join(ABAPGIT_REPO_DIR, "src")


def _latest_iteration_files(ticket_key: str):
    ticket_dir = os.path.join(GENERATED_DIR, ticket_key)
    if not os.path.isdir(ticket_dir):
        raise SystemExit(f"No generated files found for {ticket_key!r} in {ticket_dir}")

    pattern = re.compile(r"^v(\d+)_(.+\.(?:abap|tabl|struc))$")
    by_iteration = {}
    for fname in os.listdir(ticket_dir):
        m = pattern.match(fname)
        if m:
            by_iteration.setdefault(int(m.group(1)), []).append(fname)

    if not by_iteration:
        raise SystemExit(f"No .abap/.tabl/.struc files found under {ticket_dir}")

    latest = max(by_iteration)
    return latest, [os.path.join(ticket_dir, f) for f in by_iteration[latest]]


def _detect_abap_object(source: str):
    """Return (object_type, object_name) or (None, None) if not recognized."""
    m = re.search(r"^\s*REPORT\s+(\w+)", source, re.IGNORECASE | re.MULTILINE)
    if m:
        return "prog", m.group(1).upper()

    m = re.search(r"^\s*CLASS\s+(\w+)\s+DEFINITION\s+PUBLIC", source, re.IGNORECASE | re.MULTILINE)
    if m:
        return "clas", m.group(1).upper()

    return None, None


def _prog_xml(name: str, description: str) -> str:
    description = description[:60]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_PROG" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <PROGDIR>
    <NAME>{name}</NAME>
    <SUBC>1</SUBC>
    <RSTAT>P</RSTAT>
    <RLOAD>E</RLOAD>
    <FIXPT>X</FIXPT>
    <UCCHECK>X</UCCHECK>
   </PROGDIR>
   <TPOOL>
    <item>
     <ID>R</ID>
     <ENTRY>{description}</ENTRY>
     <LENGTH>{len(description)}</LENGTH>
    </item>
   </TPOOL>
  </asx:values>
 </asx:abap>
</abapGit>
"""


def _clas_xml(name: str, description: str) -> str:
    description = description[:60]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_CLAS" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <VSEOCLASS>
    <CLSNAME>{name}</CLSNAME>
    <LANGU>E</LANGU>
    <DESCRIPT>{description}</DESCRIPT>
    <STATE>1</STATE>
    <CLSCCINCL>X</CLSCCINCL>
    <FIXPT>X</FIXPT>
    <UNICODE>X</UNICODE>
   </VSEOCLASS>
  </asx:values>
 </asx:abap>
</abapGit>
"""


# ------------------------------------------------------------------
# Dictionary objects (.tabl / .struc) -- see CLAUDE.md for the source
# text format this parses.
# ------------------------------------------------------------------

# Inline built-in type -> (DATATYPE, LENG, DECIMALS, INTTYPE, INTLEN).
# Best-effort technical attributes; referencing a real data element
# (anything not matching these patterns) is the safer path since SAP
# derives these automatically on activation instead.
_INLINE_TYPES = [
    (re.compile(r"^CHAR(\d+)$"), lambda m: ("CHAR", int(m.group(1)), 0, "C", int(m.group(1)))),
    (re.compile(r"^NUMC(\d+)$"), lambda m: ("NUMC", int(m.group(1)), 0, "C", int(m.group(1)))),
    (re.compile(r"^DEC(\d+)\.(\d+)$"), lambda m: (
        "DEC", int(m.group(1)), int(m.group(2)), "P", (int(m.group(1)) // 2) + 1
    )),
    (re.compile(r"^INT4$"), lambda m: ("INT4", 10, 0, "I", 4)),
    (re.compile(r"^INT2$"), lambda m: ("INT2", 5, 0, "s", 2)),
    (re.compile(r"^INT1$"), lambda m: ("INT1", 3, 0, "b", 1)),
    (re.compile(r"^DATS$"), lambda m: ("DATS", 8, 0, "C", 8)),
    (re.compile(r"^TIMS$"), lambda m: ("TIMS", 6, 0, "C", 6)),
    (re.compile(r"^STRING$"), lambda m: ("STRG", 0, 0, "g", 0)),
]


def _resolve_inline_type(type_str: str):
    for pattern, build in _INLINE_TYPES:
        m = pattern.match(type_str.upper())
        if m:
            return build(m)
    return None


def _parse_ddic_text(text: str) -> dict:
    """Parse the CLAUDE.md dictionary-object text format into a dict:
    {kind: 'tabl'|'struc', name, description, delivery_class, fields: [...]}
    """
    lines = [l.rstrip() for l in text.splitlines()]
    result = {"delivery_class": None, "fields": []}
    in_fields = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        if stripped.upper().startswith("TABLE:"):
            result["kind"] = "tabl"
            result["name"] = stripped.split(":", 1)[1].strip().upper()
        elif stripped.upper().startswith("STRUCTURE:"):
            result["kind"] = "struc"
            result["name"] = stripped.split(":", 1)[1].strip().upper()
        elif stripped.upper().startswith("DESCRIPTION:"):
            result["description"] = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("DELIVERY_CLASS:"):
            result["delivery_class"] = stripped.split(":", 1)[1].strip().upper()
        elif stripped.upper().startswith("FIELDS:"):
            in_fields = True
        elif in_fields and "|" in stripped:
            parts = [p.strip() for p in stripped.split("|")]
            if result.get("kind") == "tabl":
                name, key, ftype = parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""
                desc = parts[3] if len(parts) > 3 else ""
                result["fields"].append({
                    "name": name.upper(), "key": key.upper() == "KEY", "type": ftype, "description": desc,
                })
            else:
                name, ftype = parts[0], parts[1] if len(parts) > 1 else ""
                desc = parts[2] if len(parts) > 2 else ""
                result["fields"].append({
                    "name": name.upper(), "key": False, "type": ftype, "description": desc,
                })

    if "kind" not in result or "name" not in result or not result["fields"]:
        raise ValueError("Could not parse TABLE:/STRUCTURE: name or FIELDS: from dictionary object text")
    return result


def _dd03p_field_xml(field: dict, position: int, keypos: int) -> str:
    inline = _resolve_inline_type(field["type"]) if field["type"] else None
    keyflag = "X" if field["key"] else ""
    notnull = "X" if field["key"] else ""
    keypos_str = f"{keypos:02d}" if field["key"] else "00"

    if inline is None:
        # Reference an existing data element -- SAP fills in the
        # technical attributes (DATATYPE/LENG/etc.) from it on activation.
        return f"""    <DD03P>
     <FIELDNAME>{field['name']}</FIELDNAME>
     <KEYFLAG>{keyflag}</KEYFLAG>
     <ROLLNAME>{field['type']}</ROLLNAME>
     <NOTNULL>{notnull}</NOTNULL>
     <POSITION>{position:04d}</POSITION>
     <KEYPOS>{keypos_str}</KEYPOS>
     <ADMINFIELD>0</ADMINFIELD>
    </DD03P>
"""
    datatype, leng, decimals, inttype, intlen = inline
    return f"""    <DD03P>
     <FIELDNAME>{field['name']}</FIELDNAME>
     <KEYFLAG>{keyflag}</KEYFLAG>
     <NOTNULL>{notnull}</NOTNULL>
     <DATATYPE>{datatype}</DATATYPE>
     <LENG>{leng:06d}</LENG>
     <DECIMALS>{decimals:06d}</DECIMALS>
     <POSITION>{position:04d}</POSITION>
     <KEYPOS>{keypos_str}</KEYPOS>
     <ADMINFIELD>0</ADMINFIELD>
     <INTTYPE>{inttype}</INTTYPE>
     <INTLEN>{intlen:06d}</INTLEN>
     <DDTEXT>{field['description'][:60]}</DDTEXT>
    </DD03P>
"""


def _fields_xml(fields: list) -> str:
    out = []
    keypos = 0
    for i, field in enumerate(fields):
        if field["key"]:
            keypos += 1
        out.append(_dd03p_field_xml(field, i + 1, keypos))
    return "".join(out)


def _tabl_xml(parsed: dict) -> str:
    name = parsed["name"]
    description = parsed.get("description", "")[:60]
    delivery_class = parsed.get("delivery_class") or "A"
    fields_xml = _fields_xml(parsed["fields"])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_TABL" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <DD02V>
    <TABNAME>{name}</TABNAME>
    <DDLANGUAGE>E</DDLANGUAGE>
    <TABCLASS>TRANSP</TABCLASS>
    <DDTEXT>{description}</DDTEXT>
    <CONTFLAG>{delivery_class}</CONTFLAG>
    <EXCLASS>1</EXCLASS>
   </DD02V>
   <DD09L>
    <TABNAME>{name}</TABNAME>
    <AS4LOCAL>A</AS4LOCAL>
    <TABKAT>0</TABKAT>
    <TABART>APPL0</TABART>
    <BUFALLOW>N</BUFALLOW>
   </DD09L>
   <DD03P_TABLE>
{fields_xml}   </DD03P_TABLE>
  </asx:values>
 </asx:abap>
</abapGit>
"""


def _struc_xml(parsed: dict) -> str:
    name = parsed["name"]
    description = parsed.get("description", "")[:60]
    fields_xml = _fields_xml(parsed["fields"])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<abapGit version="v1.0.0" serializer="LCL_OBJECT_TABL" serializer_version="v1.0.0">
 <asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">
  <asx:values>
   <DD02V>
    <TABNAME>{name}</TABNAME>
    <DDLANGUAGE>E</DDLANGUAGE>
    <TABCLASS>INTTAB</TABCLASS>
    <DDTEXT>{description}</DDTEXT>
    <EXCLASS>1</EXCLASS>
   </DD02V>
   <DD03P_TABLE>
{fields_xml}   </DD03P_TABLE>
  </asx:values>
 </asx:abap>
</abapGit>
"""


def convert(ticket_key: str, push: bool = False):
    iteration, files = _latest_iteration_files(ticket_key)
    print(f"Converting iteration v{iteration} for {ticket_key} ({len(files)} file(s))")

    os.makedirs(ABAPGIT_SRC_DIR, exist_ok=True)
    converted, skipped = [], []

    for path in files:
        ext = path.rsplit(".", 1)[-1].lower()
        with open(path) as f:
            source = f.read()

        if ext in ("tabl", "struc"):
            try:
                parsed = _parse_ddic_text(source)
            except ValueError as e:
                print(f"Skipping {os.path.basename(path)}: {e}", file=sys.stderr)
                skipped.append(os.path.basename(path))
                continue
            lower_name = parsed["name"].lower()
            xml_path = os.path.join(ABAPGIT_SRC_DIR, f"{lower_name}.{parsed['kind']}.xml")
            xml_content = (_tabl_xml if parsed["kind"] == "tabl" else _struc_xml)(parsed)
            with open(xml_path, "w") as f:
                f.write(xml_content)
            converted.append(f"{lower_name}.{parsed['kind']}.xml")
            continue

        obj_type, obj_name = _detect_abap_object(source)
        if obj_type is None:
            skipped.append(os.path.basename(path))
            continue

        lower_name = obj_name.lower()
        abap_path = os.path.join(ABAPGIT_SRC_DIR, f"{lower_name}.{obj_type}.abap")
        xml_path = os.path.join(ABAPGIT_SRC_DIR, f"{lower_name}.{obj_type}.xml")

        with open(abap_path, "w") as f:
            f.write(source)
        xml_content = (_prog_xml if obj_type == "prog" else _clas_xml)(
            obj_name, f"{ticket_key}: generated by SAP Code Generator"
        )
        with open(xml_path, "w") as f:
            f.write(xml_content)

        converted.append(f"{lower_name}.{obj_type}.abap")

    print(f"Converted: {converted}")
    if skipped:
        print(f"Skipped (unrecognized object type, handle manually): {skipped}")

    if push and converted:
        subprocess.run(["git", "add", "-A"], cwd=ABAPGIT_REPO_DIR, check=True)
        commit_msg = f"{ticket_key}: v{iteration} — " + ", ".join(converted)
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg], cwd=ABAPGIT_REPO_DIR, capture_output=True, text=True
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            print(result.stdout, result.stderr, file=sys.stderr)
            raise SystemExit("git commit failed")
        subprocess.run(["git", "push"], cwd=ABAPGIT_REPO_DIR, check=True)
        print("Pushed to remote.")

    return converted, skipped


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 export_to_abapgit.py <ticket-key> [--push]", file=sys.stderr)
        sys.exit(1)
    convert(sys.argv[1], push="--push" in sys.argv[2:])
