import io
import json
import mimetypes
import os
import zipfile
import tarfile
from pathlib import Path
from typing import Tuple

import magic
import pandas as pd

# Docling imports
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import VlmPipelineOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter

# Optional: PyxTxt for broader extraction (install extras if needed)
try:
    from pyxtxt import extract
    HAS_PYXTXT = True
except ImportError:
    HAS_PYXTXT = False

# --------------------------------------------------------------------------------
#  Docling Setup (Granite Docling)
# --------------------------------------------------------------------------------

vlm_opts = VlmPipelineOptions()
docling_converter = DocumentConverter(
    format_options={InputFormat.PDF: PdfPipelineOptions(pipeline_cls=None, pipeline_options=vlm_opts)}
)

# --------------------------------------------------------------------------------
#  Supported Dispatcher Groups
# --------------------------------------------------------------------------------

DOCLING_EXTS = {".pdf", ".docx", ".pptx", ".html", ".htm", ".xlsx", ".csv", ".txt", ".md", ".png",
                ".jpeg", ".jpg", ".bmp", ".tiff", ".webp"}  # Docling covers many

SPREADSHEET_EXTS = {".csv", ".xlsx", ".xls", ".ods", ".tsv"}
ARCHIVE_EXTS = {".zip", ".tar", ".gz", ".tar.gz", ".7z"}
CODE_TEXT_EXTS = {".py", ".js", ".ts", ".json", ".xml", ".yaml", ".yml", ".java", ".c", ".cpp", ".h", ".cs", ".sql", ".ini", ".log"}

AUDIO_VIDEO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".mp4", ".mov", ".wmv", ".avi", ".mkv"}

# --------------------------------------------------------------------------------
#  Conversion Functions
# --------------------------------------------------------------------------------

def guess_extension(filename: str, mime: str = None) -> str:
    """Get extension: prefer filename suffix, fallback to MIME."""
    ext = Path(filename).suffix.lower()
    if ext:
        return ext
    if mime:
        ext = mimetypes.guess_extension(mime) or ""
    return ext.lower()

def convert_bytes(file_bytes: bytes, filename: str, mime: str = None) -> Tuple[dict, str]:
    """
    Convert any bytes into (json_struct, markdown).
    """
    ext = guess_extension(filename, mime)

    # -- Archive (unpack to process each file if needed)
    if ext in ARCHIVE_EXTS:
        return handle_archive(file_bytes, filename)

    # -- Audio/Video (requires extra libs if available)
    if ext in AUDIO_VIDEO_EXTS:
        return handle_audio_video(file_bytes, filename)

    # -- Code/Text
    if ext in CODE_TEXT_EXTS:
        return handle_text_bytes(file_bytes)

    # -- Docling formats
    if ext in DOCLING_EXTS:
        return convert_with_docling(file_bytes, filename)

    # -- Fallback: raw try via PyxTxt if installed
    if HAS_PYXTXT:
        try:
            return convert_with_pyxxt(file_bytes, filename)
        except Exception:
            pass

    # Unsupported
    return {"error": f"Unsupported: {filename}"}, f"Unsupported file {filename}"

# --------------------------------------------------------------------------------
#  Handler Impl
# --------------------------------------------------------------------------------

def convert_with_docling(file_bytes: bytes, filename: str) -> Tuple[dict, str]:
    """
    Use Docling to parse into JSON/Markdown.
    """
    # Write temp file with correct extension
    tmp = Path(f"/tmp/{filename}")
    tmp.write_bytes(file_bytes)

    result = docling_converter.convert(source=str(tmp))
    doc = result.document

    json_struct = doc.model_dump()
    md_text = doc.export_to_markdown()

    tmp.unlink(missing_ok=True)
    return json_struct, md_text

def handle_text_bytes(file_bytes: bytes) -> Tuple[dict, str]:
    """
    Simple text or code bytes.
    """
    text = file_bytes.decode("utf-8", errors="replace")
    return {"text": text}, text

def handle_spreadsheet_bytes(file_bytes: bytes, ext: str) -> Tuple[dict, str]:
    """
    Spreadsheet → JSON records + simple MD table.
    """
    bio = io.BytesIO(file_bytes)
    if ext in {".xls", ".xlsx", ".ods"}:
        df = pd.read_excel(bio)
    else:  # CSV/TSV
        sep = "\t" if ext == ".tsv" else ","
        df = pd.read_csv(bio, sep=sep)

    json_struct = df.to_dict(orient="records")
    md = df.to_markdown()
    return {"table": json_struct}, md

def handle_archive(file_bytes: bytes, filename: str) -> Tuple[dict, str]:
    """
    Unpack archive and process listing.
    """
    ext = Path(filename).suffix.lower()
    info = {}
    md = f"Archive: {filename}\n"
    # ZIP
    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            for name in z.namelist():
                md += f"- {name}\n"
                info[name] = "in archive"
    elif ext in {".tar", ".gz", ".tar.gz"}:
        with tarfile.open(fileobj=io.BytesIO(file_bytes), mode="r:*") as t:
            for member in t.getmembers():
                md += f"- {member.name}\n"
                info[member.name] = "in archive"
    else:
        md += "Unsupported archive format"
    return {"archive_contents": info}, md

def handle_audio_video(file_bytes: bytes, filename: str) -> Tuple[dict, str]:
    """
    Transcribe audio/video if PyxTxt is installed (Whisper).
    Otherwise return simple metadata.
    """
    if HAS_PYXTXT:
        out = extract(io.BytesIO(file_bytes), filename)
        return {"transcript": out.text}, out.text
    # Fallback
    return {"info": f"Audio/video received ({filename})"}, f"Audio/video: {filename}"

def convert_with_pyxxt(file_bytes: bytes, filename: str) -> Tuple[dict, str]:
    """
    PyxTxt fallback extractor (text + OCR + transcription).
    """
    out = extract(io.BytesIO(file_bytes), filename)
    return {"text": out.text}, out.text

