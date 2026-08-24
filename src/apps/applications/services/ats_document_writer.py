from pathlib import Path
import shutil
import textwrap


class AtsDocumentWriter:
    """Write Simplify/ATS-like single-column Resume.pdf and Cover-Letter.pdf."""

    resume_name = "Resume.pdf"
    cover_letter_name = "Cover-Letter.pdf"
    original_suffix = ".original.pdf"

    def write_resume(self, folder, text, source_path=None):
        return self._write_named_pdf(
            folder,
            filename=self.resume_name,
            title="Resume",
            text=text,
            source_path=source_path,
        )

    def write_cover_letter(self, folder, text, source_path=None):
        return self._write_named_pdf(
            folder,
            filename=self.cover_letter_name,
            title="Cover Letter",
            text=text,
            source_path=source_path,
        )

    def _write_named_pdf(self, folder, filename, title, text, source_path=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        source = Path(source_path) if source_path else None
        backup = ""
        if (
            source is not None
            and source.exists()
            and source.resolve() == target.resolve()
        ):
            backup_path = folder / f"{target.stem}{self.original_suffix}"
            if not backup_path.exists():
                shutil.copy2(source, backup_path)
            backup = backup_path.name
        self.write_plain_pdf(target, title=title, body=text)
        self._write_plain_docx(target.with_suffix(".docx"), title=title, body=text)
        return {"path": target, "backup": backup}

    @classmethod
    def write_plain_pdf(cls, path, title, body):
        lines = cls._wrap_lines(f"{title}\n\n{body}")
        commands = ["BT /F1 11 Tf 72 720 Td 16 TL"]
        commands.extend(f"({cls._pdf_escape(line)}) Tj T*" for line in lines)
        commands.append("ET")
        content_bytes = ("\n".join(commands) + "\n").encode("latin-1")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
            ),
            b"<< /Length %d >>\nstream\n" % len(content_bytes)
            + content_bytes
            + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        output = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(output))
            output.extend(f"{index} 0 obj\n".encode("ascii"))
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n"
            ).encode("ascii")
        )
        Path(path).write_bytes(bytes(output))

    @staticmethod
    def _write_plain_docx(path, title, body):
        from docx import Document
        from docx.enum.text import WD_LINE_SPACING
        from docx.shared import Inches, Pt

        document = Document()
        for section in document.sections:
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)
        heading = document.add_paragraph(title)
        heading.runs[0].bold = True
        heading.runs[0].font.size = Pt(14)
        heading.runs[0].font.name = "Calibri"
        for block in str(body or "").splitlines() or [""]:
            paragraph = document.add_paragraph(block if block.strip() else "")
            paragraph.paragraph_format.space_after = Pt(6)
            paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
            for run in paragraph.runs:
                run.font.size = Pt(11)
                run.font.name = "Calibri"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        document.save(path)

    @classmethod
    def _wrap_lines(cls, text, width=90):
        lines = []
        for raw in str(text or "").replace("\r\n", "\n").split("\n"):
            chunk = cls._latin1(raw)
            if not chunk.strip():
                lines.append("")
                continue
            lines.extend(textwrap.wrap(chunk, width=width) or [""])
        return lines[:60] or [""]

    @staticmethod
    def _latin1(value):
        return str(value or "").encode("latin-1", errors="replace").decode("latin-1")

    @staticmethod
    def _pdf_escape(value):
        return (
            str(value or "")
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
